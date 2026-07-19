# Strategy+Execution instance, cross-venue arb mode (paper trading).
# Tails BOTH venue queues in one process; signals on the Coinbase/OKX basis
# deviating from its EMA; every signal places an atomic two-leg order pair.
# Deliberately unprofitable at current fee tiers — it exists to exercise the
# multi-queue merge, two-leg risk, and cross-venue sim-fill machinery.
$Java = Join-Path $env:USERPROFILE '.jdks\ms-21.0.11\bin\java.exe'
Set-Location "$PSScriptRoot\..\..\src\strategy-execution"
& $Java `
    '-Dstrategy.mode=arb' `
    '-Dmd.queue.dirs=../marketdata-coinbase/queues/md-coinbase,../marketdata-okx/queues/md-okx' `
    '-Darb.symbol.BTC=COINBASE:BTC-USD,OKX:BTC-USDT' `
    '-Darb.symbol.ETH=COINBASE:ETH-USD,OKX:ETH-USDT' `
    '-Daudit.queue.dir=queues/signals-audit-arb' `
    '-Dorders.dir=orders-arb' `
    '-Dmetrics.reports-dir=reports-arb' `
    -jar target\strategy-execution.jar
