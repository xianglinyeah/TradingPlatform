# Load MdTopExporter output into hft.md_top (and optionally hft.md_stats).
# Idempotent per venue: each queue dir is one venue's full history, so
# existing rows for that venue are deleted before the insert.
#   .\import_md.ps1 -File <md_top_xxx.jsonl> -Venue COINBASE [-StatsFile <md_stats_xxx.jsonl>]
param(
    [Parameter(Mandatory)][string]$File,
    [Parameter(Mandatory)][string]$Venue,
    [string]$StatsFile
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\ch.ps1"

function Import-VenueFile([string]$table, [string]$path) {
    $existing = [long](Invoke-Ch -Query "SELECT count() FROM $table WHERE venue='$Venue'").Trim()
    if ($existing -gt 0) {
        Write-Host "deleting $existing existing $table rows for venue=$Venue"
        Invoke-Ch -Query "DELETE FROM $table WHERE venue='$Venue'" | Out-Null
    }
    Invoke-Ch -Query "INSERT INTO $table FORMAT JSONEachRow" -BodyFile $path | Out-Null
}

Import-VenueFile "hft.md_top" $File
if ($StatsFile) { Import-VenueFile "hft.md_stats" $StatsFile }
Invoke-Ch -Query "SELECT venue, product, count() AS rows, min(ts) AS first, max(ts) AS last FROM hft.md_top WHERE venue='$Venue' GROUP BY venue, product FORMAT PrettyCompact"
