# Pulls the EC2 strategy-execution orders/sim-fills JSONL files down from S3
# (synced there every ~1min by a cron job on the instance, see
# sync_orders_to_s3.sh / EC2 crontab) and imports them via the existing
# import_runs.ps1 (row-count-based incremental idempotency -- cheap, no
# Chronicle Queue / Java involved, unlike the md_stats/md_top pipeline).
#
#   .\import_orders_live.ps1
param(
    [string]$Bucket = "hft-md-archive-439155107181",
    [string]$Region = "us-east-1",
    [string]$LocalDir = "$PSScriptRoot\..\..\hft\strategy-execution\orders-ec2"
)
$ErrorActionPreference = "Stop"
$env:PATH += ";C:\Program Files\Amazon\AWSCLIV2"

aws s3 sync "s3://$Bucket/orders-ec2/" $LocalDir --region $Region --only-show-errors
if ($LASTEXITCODE -ne 0) {
    Write-Warning "aws s3 sync failed (exit $LASTEXITCODE) -- skipping import this cycle"
    exit 0
}

& "$PSScriptRoot\import_runs.ps1" -Root $LocalDir
