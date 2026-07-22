# Process A, OKX venue: WS -> book -> Chronicle queue (queues/md-okx).
# Public books channel — no credentials needed. Requires the local proxy.
$Java = Join-Path $env:USERPROFILE '.jdks\ms-21.0.11\bin\java.exe'
Set-Location "$PSScriptRoot\..\marketdata-okx"
& $Java -jar target\marketdata-okx.jar
