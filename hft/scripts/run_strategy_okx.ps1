# Strategy+Execution instance, OKX venue (paper trading).
# Second instance of the same jar: per-venue queue + isolated output dirs.
# sim.fee-bps=10: OKX regular-tier taker fee (~0.10%), vs the Coinbase
# 60 bps default in strategy.properties — wrong fee = wrong PnL verdict.
$Java = Join-Path $env:USERPROFILE '.jdks\ms-21.0.11\bin\java.exe'
Set-Location "$PSScriptRoot\..\strategy-execution"
& $Java `
    '-Dmd.queue.dir=../marketdata-okx/queues/md-okx' `
    '-Daudit.queue.dir=queues/signals-audit-okx' `
    '-Dorders.dir=orders-okx' `
    '-Dmetrics.reports-dir=reports-okx' `
    '-Dsim.fee-bps=10' `
    -jar target\strategy-execution.jar
