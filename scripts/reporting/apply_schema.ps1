# Apply scripts/reporting/schema.sql to ClickHouse, one statement at a time
# (the CH HTTP interface takes a single statement per request).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\ch.ps1"

$sql = Get-Content "$PSScriptRoot\schema.sql" -Raw
# Strip line comments, then split on ";" statement terminators.
$noComments = ($sql -split "`n" | Where-Object { $_.TrimStart() -notmatch '^--' }) -join "`n"
$statements = $noComments -split ";" | ForEach-Object { $_.Trim() } | Where-Object { $_ }

foreach ($stmt in $statements) {
    $first = ($stmt -split "`n")[0].Trim()
    Write-Host "==> $first"
    Invoke-Ch -Query $stmt | Out-Null
}
Write-Host "Schema applied. Tables now:"
Invoke-Ch -Query "SELECT name, engine FROM system.tables WHERE database='hft' FORMAT PrettyCompact"
