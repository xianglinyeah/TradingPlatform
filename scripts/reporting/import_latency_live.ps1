# Pulls the periodic (~10s) "[latency] segment: n=... p50=... p99=..." lines
# that marketdata-coinbase / strategy-execution already emit continuously to
# journald on the EC2 box, and inserts them into hft.latency_reports as a
# live-growing time series (label=ec2-live, distinct from the one-off
# "ec2" snapshot imported by import_latency.ps1 from a shutdown report file).
#
# Deliberately does NOT touch the EC2 processes (no restart) -- these lines
# are already being produced by the running services; this script only reads
# recent journal output via SSM send-command (no SSH/tunnel dependency) and
# is safe to run on a tight interval (e.g. every 1 min via Task Scheduler).
#
#   .\import_latency_live.ps1 [-InstanceId i-xxxx] [-Region us-east-1] [-Label ec2-live]
param(
    [string]$InstanceId = "i-0cfb707e511a36bd1",
    [string]$Region = "us-east-1",
    [string]$Label = "ec2-live"
)
$ErrorActionPreference = "Stop"
$env:PATH += ";C:\Program Files\Amazon\AWSCLIV2"
. "$PSScriptRoot\ch.ps1"

# Only interval lines ("[latency] ", not "[latency-cum] ") -- cumulative
# whole-run percentiles belong to the end-of-run report table, not this feed.
# min= is present for strategy-execution's segments but absent for
# marketdata-coinbase's (LatencyTracker.describe() never prints it) -- optional group, default 0.
$segRe = '\[latency\]\s+(?<seg>[^:]+):\s+n=(?<n>\d+)\s+(?:min=(?<min>-?[\d.]+)us\s+)?p50=(?<p50>-?[\d.]+)us\s+p99=(?<p99>-?[\d.]+)us\s+p99\.9=(?<p999>-?[\d.]+)us\s+max=(?<max>-?[\d.]+)us'

$lastEpoch = (Invoke-Ch -Query "SELECT toUnixTimestamp(max(reportTs)) FROM hft.latency_reports WHERE label='$Label'").Trim()
if (-not $lastEpoch -or $lastEpoch -eq '0') {
    $sinceEpoch = [DateTimeOffset]::UtcNow.AddMinutes(-5).ToUnixTimeSeconds()
} else {
    $sinceEpoch = [long]$lastEpoch
}

# Filter server-side (grep) before it comes back over SSM -- unfiltered
# journal output (esp. right after a restart) easily exceeds the ~24KB
# StandardOutputContent truncation limit and silently drops the tail, which
# is exactly where the lines we want tend to sort chronologically.
$remoteCmd = "journalctl -u hft-md-coinbase -u hft-strategy-coinbase -o short-iso-precise --no-pager --since '@$sinceEpoch' | grep '\[latency\] ' || true"
$paramsJson = (@{ commands = @($remoteCmd) } | ConvertTo-Json -Compress)
$paramsFile = Join-Path $env:TEMP "import_latency_live_ssm_params.json"
Set-Content -Path $paramsFile -Value $paramsJson -Encoding ASCII

$cmdId = aws ssm send-command --region $Region --instance-ids $InstanceId `
    --document-name "AWS-RunShellScript" `
    --parameters "file://$paramsFile" `
    --query 'Command.CommandId' --output text
if (-not $cmdId) { throw "send-command failed to return a CommandId" }

$status = "Pending"
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    $status = aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query 'Status' --output text 2>$null
    if ($status -eq 'Success' -or $status -eq 'Failed') { break }
}
if ($status -ne 'Success') {
    Write-Warning "SSM command did not succeed (status=$status) -- instance may be unreachable, skipping this cycle"
    exit 0
}
$output = aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query 'StandardOutputContent' --output text

$rows = @()
foreach ($line in ($output -split "`r?`n")) {
    if ($line -match '^(?<ts>\d{4}-\d{2}-\d{2}T[\d:.]+[+-]\d{4})\s+\S+\s+\S+:\s+(?<msg>.*)$') {
        $tsRaw = $Matches['ts']
        $msg = $Matches['msg']
        if ($msg -match $segRe) {
            $dt = [DateTimeOffset]::Parse($tsRaw)
            $tsCh = $dt.UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss.ffffff")
            $minUs = if ($Matches['min']) { $Matches['min'] } else { 0 }
            $rows += ('{{"label":"{0}","reportTs":"{1}","segment":"{2}","n":{3},"minUs":{4},"p50Us":{5},"p99Us":{6},"p999Us":{7},"maxUs":{8}}}' -f `
                $Label, $tsCh, $Matches['seg'].Trim(), $Matches['n'], $minUs, $Matches['p50'], $Matches['p99'], $Matches['p999'], $Matches['max'])
        }
    }
}

if ($rows) {
    $q = "INSERT INTO hft.latency_reports SETTINGS date_time_input_format='best_effort' FORMAT JSONEachRow"
    Invoke-Ch -Query $q -Body ($rows -join "`n") | Out-Null
    Write-Host "inserted $($rows.Count) rows (since epoch $sinceEpoch)"
} else {
    Write-Host "no new rows (since epoch $sinceEpoch)"
}
