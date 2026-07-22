# Strategy+Execution instance, Coinbase venue (paper trading).
# Uses strategy.properties defaults: md-coinbase queue, 60 bps taker fee.
$Java = Join-Path $env:USERPROFILE '.jdks\ms-21.0.11\bin\java.exe'
Set-Location "$PSScriptRoot\..\strategy-execution"
& $Java -jar target\strategy-execution.jar
