# One-shot reporting sync: fetch hot-path data to local disk, then ingest it
# into ClickHouse. Safe to run any time, including while the hot path is live
# (Chronicle queues support concurrent readers; torn JSONL tail lines are
# skipped and picked up next round). Never touches the hot path itself.
#
#   .\sync_reporting.ps1                 # local source (default)
#
# Structure is deliberately two-stage:
#   Stage 1 (fetch)  — resolve the source into local directories. The ONLY
#                      part that changes when the hot path moves to EC2:
#                      add an 'ec2' branch that s3-syncs archives + JSONL
#                      into $Staging and points $runRoot/$queues there.
#   Stage 2 (ingest) — source-agnostic: import_runs.ps1 (orders/fills,
#                      incremental by row count) + MdTopExporter/import_md.ps1
#                      (md top-of-book, full re-export per venue).
param(
    [ValidateSet("local")][string]$Source = "local",
    [string]$Staging = "D:\TradingPlatform\data\reporting-staging"
)
$ErrorActionPreference = "Stop"

# ---------------- Stage 1: fetch ----------------
switch ($Source) {
    "local" {
        $runRoot = "D:\TradingPlatform\src\strategy-execution"
        $queues = @(
            @{ Venue = "COINBASE"; Dir = "D:\TradingPlatform\src\marketdata-coinbase\queues\md-coinbase" },
            @{ Venue = "OKX";      Dir = "D:\TradingPlatform\src\marketdata-okx\queues\md-okx" }
        )
    }
    # "ec2" { ... aws s3 sync s3://<bucket>/md-archive "$Staging\..." ; restore; set $runRoot/$queues ... }
}

# ---------------- Stage 2: ingest ----------------
Write-Host "=== orders / sim_fills ==="
& "$PSScriptRoot\import_runs.ps1" -Root $runRoot

Write-Host ""
Write-Host "=== md_top (queue replay) ==="
New-Item -ItemType Directory -Force $Staging | Out-Null
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = "C:\Users\xiang\.jdks\openjdk-25.0.2" }
$java = Join-Path $env:JAVA_HOME "bin\java.exe"
$jar = "D:\TradingPlatform\src\marketdata-coinbase\target\marketdata-coinbase.jar"
if (-not (Test-Path $jar)) { throw "shaded jar not found: $jar - build marketdata-coinbase first" }
$chronicleFlags = @(
    "--add-exports=java.base/jdk.internal.ref=ALL-UNNAMED",
    "--add-exports=java.base/sun.nio.ch=ALL-UNNAMED",
    "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
    "--add-opens=java.base/java.lang=ALL-UNNAMED",
    "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
    "--add-opens=java.base/java.io=ALL-UNNAMED",
    "--add-opens=java.base/java.util=ALL-UNNAMED"
)

foreach ($q in $queues) {
    if (-not (Test-Path $q.Dir)) {
        Write-Warning "queue dir missing, skipping venue $($q.Venue): $($q.Dir)"
        continue
    }
    $out = Join-Path $Staging ("md_top_" + $q.Venue.ToLower() + ".jsonl")
    $stats = Join-Path $Staging ("md_stats_" + $q.Venue.ToLower() + ".jsonl")
    Write-Host "exporting $($q.Venue) from $($q.Dir)"
    & $java @chronicleFlags -cp $jar com.yexl.trading.marketdata.tools.MdTopExporter $q.Dir $out $stats
    if ($LASTEXITCODE -ne 0) { throw "MdTopExporter failed for $($q.Venue) (exit $LASTEXITCODE)" }
    & "$PSScriptRoot\import_md.ps1" -File $out -Venue $q.Venue -StatsFile $stats
}

Write-Host ""
Write-Host "=== latency reports ==="
& "$PSScriptRoot\import_latency.ps1" -Root $runRoot

Write-Host ""
Write-Host "sync complete."
