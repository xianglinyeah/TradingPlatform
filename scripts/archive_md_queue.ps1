# Archive rolled Chronicle Queue market-data files (zstd via Windows bsdtar).
#
# The queue is the backtest source of truth: archived days replay bit-identically
# through strategy-execution's stream-clock mode. Only files whose date-part is
# BEFORE today are touched — the current cycle file is memory-mapped by the live
# publisher and must be left alone.
#
# Usage:
#   .\archive_md_queue.ps1                          # archive rolled days (originals kept)
#   .\archive_md_queue.ps1 -Prune                   # archive, then delete verified originals
#   .\archive_md_queue.ps1 -Restore 20260718 -RestoreDest D:\tmp\replay-0718
#     -> restores that day + metadata.cq4t into a fresh dir ready for
#        java -Dclock.mode=stream -Dmd.queue.dir=<dir> -jar strategy-execution.jar
#
# Each archived file is round-trip verified (decompress + SHA256 compare) before
# it is considered archived; -Prune deletes originals only after that check.
# catalog.jsonl in the archive dir records file/date/hash/sizes per entry.

param(
    [string]$QueueDir = "D:\TradingPlatform\src\marketdata-coinbase\queues\md-coinbase",
    [string]$ArchiveRoot = "D:\TradingPlatform\data\md-archive",
    [switch]$Prune,
    [string]$Restore,
    [string]$RestoreDest
)

$ErrorActionPreference = 'Stop'
$queueName = Split-Path $QueueDir -Leaf
$archiveDir = Join-Path $ArchiveRoot $queueName

function Get-Sha256([string]$path) {
    (Get-FileHash $path -Algorithm SHA256).Hash
}

# ---------------- Restore mode ----------------
if ($Restore) {
    if (-not $RestoreDest) { throw "-Restore requires -RestoreDest <dir>" }
    $archive = Join-Path $archiveDir "$($Restore)F.tar.zst"
    if (-not (Test-Path $archive)) { throw "No archive for $Restore at $archive" }
    New-Item -ItemType Directory -Force $RestoreDest | Out-Null
    tar --zstd -xf $archive -C $RestoreDest
    if ($LASTEXITCODE -ne 0) { throw "tar extract failed ($LASTEXITCODE)" }
    $meta = Join-Path $archiveDir 'metadata.cq4t'
    if (Test-Path $meta) { Copy-Item $meta $RestoreDest -Force }
    Write-Output "Restored $Restore -> $RestoreDest"
    Get-ChildItem $RestoreDest | ForEach-Object { Write-Output ("  {0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
    exit 0
}

# ---------------- Archive mode ----------------
if (-not (Test-Path $QueueDir)) { throw "Queue dir not found: $QueueDir" }
New-Item -ItemType Directory -Force $archiveDir | Out-Null
$catalog = Join-Path $archiveDir 'catalog.jsonl'
$today = Get-Date -Format 'yyyyMMdd'
$archived = 0; $skipped = 0

foreach ($f in Get-ChildItem $QueueDir -Filter '*.cq4' | Sort-Object Name) {
    if ($f.BaseName -notmatch '^(\d{8})') {
        Write-Output "SKIP  $($f.Name) (no date prefix)"
        $skipped++; continue
    }
    $date = $Matches[1]
    if ($date -ge $today) {
        Write-Output "SKIP  $($f.Name) (current cycle — live writer may hold it)"
        $skipped++; continue
    }
    $dest = Join-Path $archiveDir "$($f.BaseName).tar.zst"
    if (Test-Path $dest) {
        Write-Output "SKIP  $($f.Name) (already archived)"
        # Prune may still apply to an already-verified archive from a previous run.
        if ($Prune) { Remove-Item $f.FullName -Force; Write-Output "PRUNE $($f.Name)" }
        $skipped++; continue
    }

    $srcHash = Get-Sha256 $f.FullName
    tar --zstd -cf $dest -C $QueueDir $f.Name
    if ($LASTEXITCODE -ne 0) { throw "tar compress failed for $($f.Name) ($LASTEXITCODE)" }

    # Round-trip verify before trusting the archive.
    $tmp = Join-Path $env:TEMP ("mdarch-verify-" + [guid]::NewGuid())
    New-Item -ItemType Directory $tmp | Out-Null
    try {
        tar --zstd -xf $dest -C $tmp
        if ($LASTEXITCODE -ne 0) { throw "tar verify-extract failed ($LASTEXITCODE)" }
        $rtHash = Get-Sha256 (Join-Path $tmp $f.Name)
        if ($rtHash -ne $srcHash) {
            Remove-Item $dest -Force
            throw "VERIFY FAILED for $($f.Name): $srcHash != $rtHash"
        }
    } finally {
        Remove-Item $tmp -Recurse -Force
    }

    $entry = [ordered]@{
        file = $f.Name; date = $date; srcSha256 = $srcHash
        srcBytes = $f.Length; archiveBytes = (Get-Item $dest).Length
        archivedAt = (Get-Date).ToString('o')
    } | ConvertTo-Json -Compress
    Add-Content -Path $catalog -Value $entry -Encoding utf8

    $ratio = [math]::Round(($f.Length / [double](Get-Item $dest).Length), 1)
    Write-Output ("OK    {0} -> {1:N1} MB (x{2}, verified)" -f $f.Name, ((Get-Item $dest).Length / 1MB), $ratio)
    if ($Prune) { Remove-Item $f.FullName -Force; Write-Output "PRUNE $($f.Name)" }
    $archived++
}

# Snapshot the queue metadata alongside (needed to reopen restored archives
# with the same roll cycle; small, latest copy wins).
$metaSrc = Join-Path $QueueDir 'metadata.cq4t'
if (Test-Path $metaSrc) { Copy-Item $metaSrc (Join-Path $archiveDir 'metadata.cq4t') -Force }

Write-Output "Done: $archived archived, $skipped skipped. Archive: $archiveDir"
