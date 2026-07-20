# Parse reports*/latency-*.txt run summaries into hft.latency_reports.
# Idempotent: (label, reportTs) pairs already present are skipped, so the
# rolling latency-latest.txt history gets preserved in CH across runs.
#   .\import_latency.ps1 [-Root D:\TradingPlatform\src\strategy-execution]
param(
    [string]$Root = "D:\TradingPlatform\src\strategy-execution"
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\ch.ps1"

$segRe = '^(?<seg>[^:%]+): n=(?<n>\d+) min=(?<min>-?[\d.]+)us p50=(?<p50>-?[\d.]+)us p99=(?<p99>-?[\d.]+)us p99\.9=(?<p999>-?[\d.]+)us max=(?<max>-?[\d.]+)us'

$rows = @()
foreach ($dir in Get-ChildItem $Root -Directory -Filter "reports*") {
    $label = $dir.Name -replace '^reports-?', ''
    if (-not $label) { $label = "default" }
    foreach ($file in Get-ChildItem $dir.FullName -Filter "latency-*.txt") {
        $text = Get-Content $file.FullName
        $header = $text | Select-Object -First 1
        if ($header -notmatch '(?<ts>\d{4}-\d{2}-\d{2}T[\d:.]+)Z') {
            Write-Warning "no header timestamp in $($file.FullName), skipping"
            continue
        }
        # DateTime64(6) — truncate the nano-precision header to microseconds.
        $ts = $Matches['ts'] -replace '(\.\d{6})\d*$', '$1'
        $tsCh = ($ts -replace 'T', ' ')

        $existing = [long](Invoke-Ch -Query "SELECT count() FROM hft.latency_reports WHERE label='$label' AND reportTs=toDateTime64('$tsCh', 6, 'UTC')").Trim()
        if ($existing -gt 0) {
            Write-Host "  up-to-date $label @ $tsCh ($(Split-Path $file -Leaf))"
            continue
        }
        $n = 0
        foreach ($line in $text) {
            if ($line -match $segRe) {
                $rows += ('{{"label":"{0}","reportTs":"{1}","segment":"{2}","n":{3},"minUs":{4},"p50Us":{5},"p99Us":{6},"p999Us":{7},"maxUs":{8}}}' -f `
                    $label, $tsCh, $Matches['seg'].Trim(), $Matches['n'], $Matches['min'], $Matches['p50'], $Matches['p99'], $Matches['p999'], $Matches['max'])
                $n++
            }
        }
        Write-Host "  parsed $label @ $tsCh : $n segments ($(Split-Path $file -Leaf))"
    }
}

if ($rows) {
    $q = "INSERT INTO hft.latency_reports SETTINGS date_time_input_format='best_effort' FORMAT JSONEachRow"
    Invoke-Ch -Query $q -Body ($rows -join "`n") | Out-Null
    Write-Host "inserted $($rows.Count) rows"
} else {
    Write-Host "nothing new to insert"
}
