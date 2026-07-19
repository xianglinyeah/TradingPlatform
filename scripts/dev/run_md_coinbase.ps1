# Process A, Coinbase venue: WS -> book -> Chronicle queue (queues/md-coinbase).
# Requires COINBASE_API_KEY / COINBASE_SIGNING_KEY_PATH env vars and the local proxy.
$Java = Join-Path $env:USERPROFILE '.jdks\ms-21.0.11\bin\java.exe'
Set-Location "$PSScriptRoot\..\..\src\marketdata-coinbase"
& $Java -jar target\marketdata-coinbase.jar
