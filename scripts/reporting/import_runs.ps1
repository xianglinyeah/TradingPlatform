# Import paper-trading / backtest JSONL runs into ClickHouse (hft.orders,
# hft.sim_fills). JSONL files stay the source of truth; this is a derived load.
#
#   .\import_runs.ps1                      # import everything under strategy-execution
#   .\import_runs.ps1 -Root <dir>          # a specific orders* directory
#   .\import_runs.ps1 -Force               # reimport runs already present (drops them first)
#
# Run identity: runId = "<dir label>-<timestamp of the run's orders file>".
# A sim-fills file belongs to the orders file with the closest earlier-or-equal
# timestamp within 10s (the two files are opened ~1s apart at startup).
# mode = arb when the directory name contains "arb", else imbalance.
param(
    [string]$Root = "D:\TradingPlatform\src\strategy-execution",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\ch.ps1"

function Get-FileTs([string]$name) {
    if ($name -match '(\d{8})-(\d{6})') {
        [datetime]::ParseExact($Matches[1] + $Matches[2], "yyyyMMddHHmmss", $null)
    } else { $null }
}

function Import-File([string]$table, [string]$path, [string]$runId, [string]$mode, [string]$defaultVenue) {
    # A live producer may be mid-append: drop a torn last line (no closing brace).
    $lines = @(Get-Content $path | Where-Object { $_.Trim().EndsWith('}') })
    if (-not $lines) { Write-Host "  skip empty $(Split-Path $path -Leaf)"; return }
    # Incremental idempotency by row count: JSONL files are append-only, so
    # CH rows == file lines means fully imported; anything else (new lines
    # appended since last import, or -Force) reimports the whole run — files
    # are small, DELETE+INSERT is cheaper than being clever.
    $existing = [long](Invoke-Ch -Query "SELECT count() FROM $table WHERE runId='$runId'").Trim()
    if ($existing -eq $lines.Count -and -not $Force) {
        Write-Host "  up-to-date $table <- $(Split-Path $path -Leaf) (runId=$runId rows=$existing)"
        return
    }
    if ($existing -gt 0) {
        Invoke-Ch -Query "DELETE FROM $table WHERE runId='$runId'" | Out-Null
    }
    # Early single-venue files have no venue field; the schema default
    # (COINBASE) is wrong for OKX runs, so inject the directory's venue.
    $inject = "{`"runId`":`"$runId`",`"mode`":`"$mode`","
    $injectVenue = "{`"runId`":`"$runId`",`"mode`":`"$mode`",`"venue`":`"$defaultVenue`","
    $body = ($lines | ForEach-Object {
        if ($_ -match '"venue"') { $_ -replace '^\{', $inject }
        else { $_ -replace '^\{', $injectVenue }
    }) -join "`n"
    $q = "INSERT INTO $table SETTINGS input_format_skip_unknown_fields=1 FORMAT JSONEachRow"
    Invoke-Ch -Query $q -Body $body | Out-Null
    Write-Host "  loaded $table <- $(Split-Path $path -Leaf) runId=$runId rows=$($lines.Count)"
}

$dirs = if ((Split-Path $Root -Leaf) -like "orders*") { @(Get-Item $Root) }
        else { Get-ChildItem $Root -Directory -Filter "orders*" }

foreach ($dir in $dirs) {
    $label = $dir.Name -replace '^orders-?', ''
    if (-not $label) { $label = "default" }
    $mode = if ($dir.Name -match 'arb') { "arb" } else { "imbalance" }
    $defaultVenue = if ($dir.Name -match 'okx') { "OKX" } else { "COINBASE" }
    Write-Host "$($dir.FullName)  (label=$label mode=$mode)"

    $orderFiles = @(Get-ChildItem $dir.FullName -Filter "orders-*.jsonl" | Sort-Object Name)
    $fillFiles  = @(Get-ChildItem $dir.FullName -Filter "sim-fills-*.jsonl" | Sort-Object Name)

    foreach ($of in $orderFiles) {
        $ts = Get-FileTs $of.Name
        $runId = "$label-$($ts.ToString('yyyyMMdd-HHmmss'))"
        Import-File "hft.orders" $of.FullName $runId $mode $defaultVenue
    }
    foreach ($ff in $fillFiles) {
        $fts = Get-FileTs $ff.Name
        # attach to the closest orders file at or before this fill file (≤10s gap)
        $owner = $orderFiles |
            Where-Object { ($fts - (Get-FileTs $_.Name)).TotalSeconds -ge 0 -and ($fts - (Get-FileTs $_.Name)).TotalSeconds -le 10 } |
            Select-Object -Last 1
        $runTs = if ($owner) { Get-FileTs $owner.Name } else { $fts }
        $runId = "$label-$($runTs.ToString('yyyyMMdd-HHmmss'))"
        Import-File "hft.sim_fills" $ff.FullName $runId $mode $defaultVenue
    }
}

Write-Host ""
Write-Host "Summary:"
Invoke-Ch -Query "SELECT runId, mode, count() AS fills, sum(toFloat64(fee)) AS totalFee, min(ts) AS firstFill, max(ts) AS lastFill FROM hft.sim_fills GROUP BY runId, mode ORDER BY firstFill FORMAT PrettyCompact"
