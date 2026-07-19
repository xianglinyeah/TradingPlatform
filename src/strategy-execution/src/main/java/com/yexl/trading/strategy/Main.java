package com.yexl.trading.strategy;

import com.lmax.disruptor.YieldingWaitStrategy;
import com.lmax.disruptor.dsl.Disruptor;
import com.lmax.disruptor.dsl.ProducerType;
import com.lmax.disruptor.util.DaemonThreadFactory;
import com.yexl.trading.strategy.handlers.AuditHandler;
import com.yexl.trading.strategy.handlers.OrderWriterHandler;
import com.yexl.trading.strategy.handlers.RiskCheckHandler;
import com.yexl.trading.strategy.handlers.SignalHandler;
import com.yexl.trading.strategy.md.MdTailerThread;
import com.yexl.trading.strategy.metrics.StrategyLatency;
import com.yexl.trading.strategy.sim.SimFillHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Entry point for the merged Strategy+Execution process (Process BC).
 *
 * <pre>
 *   md-tailer thread ──publish──&gt; RingBuffer&lt;StrategyEvent&gt;
 *     ──&gt; SignalHandler                (book replica + imbalance)
 *           ├──&gt; AuditHandler          (signal audit queue — parallel branch,
 *           │                           never delays an order)
 *           └──&gt; RiskCheckHandler ──&gt; OrderWriterHandler (JSONL orders)
 * </pre>
 *
 * <p>Strategy and Execution live in one process by design (single strategy,
 * single instance — no fault-isolation or fan-in requirement yet), but risk
 * check and placement stay separate handlers, and every signal is appended
 * to the audit queue: that queue is the re-split seam if a multi-strategy
 * topology ever needs Execution pulled back out.
 */
public final class Main {

    private static final Logger log = LoggerFactory.getLogger(Main.class);

    public static void main(String[] args) {
        System.setProperty("chronicle.analytics.disable", "true");
        try {
            StrategyConfig config = StrategyConfig.load();

            StrategyLatency latency = new StrategyLatency(config.signalMaxDocAgeMs, config.latencyWarmupMs);

            Disruptor<StrategyEvent> disruptor = new Disruptor<>(
                    StrategyEvent.FACTORY,
                    config.ringBufferSize,
                    DaemonThreadFactory.INSTANCE,
                    ProducerType.SINGLE,
                    new YieldingWaitStrategy()
            );

            SignalHandler signalHandler = new SignalHandler(config);
            RiskCheckHandler riskHandler = new RiskCheckHandler(config);
            OrderWriterHandler orderWriter = new OrderWriterHandler(config, latency);
            AuditHandler auditHandler = new AuditHandler(config.auditQueueDir);
            SimFillHandler simFill = new SimFillHandler(config);

            disruptor.handleEventsWith(signalHandler);
            disruptor.after(signalHandler).handleEventsWith(riskHandler, auditHandler);
            disruptor.after(riskHandler).handleEventsWith(orderWriter);
            // Sim execution sits after the measured pipeline tail: placedNanos
            // stays the latency endpoint, fills happen on later md docs anyway.
            disruptor.after(orderWriter).handleEventsWith(simFill);
            disruptor.start();

            // Backtest (stream clock): the queue is a static archive, so
            // reaching its tail means history is exhausted — trigger a normal
            // shutdown (System.exit runs the hook: drain, close, reports).
            Runnable onCaughtUp = "stream".equals(config.clockMode)
                    ? () -> {
                        log.info("Backtest: queue drained — shutting down");
                        new Thread(() -> System.exit(0), "backtest-exit").start();
                    }
                    : null;
            MdTailerThread tailer = new MdTailerThread(
                    config.mdQueueDir, config.tailFrom, disruptor.getRingBuffer(), onCaughtUp);

            ScheduledExecutorService stats = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "strategy-stats");
                t.setDaemon(true);
                return t;
            });
            final int[] cycle = {0};
            stats.scheduleAtFixedRate(() -> {
                try {
                    log.info("[stats] consumed={} pseqGaps={} signals={} approved={} rejected={} orders={} fills={} unfilled={}",
                            tailer.consumedCount(), tailer.pseqGapCount(),
                            signalHandler.signalsGeneratedCount(),
                            riskHandler.approvedCount(), riskHandler.rejectedCount(),
                            orderWriter.ordersWrittenCount(),
                            simFill.fillCount(), simFill.unfilledCount());
                    for (String line : simFill.pnlSummaryLines()) {
                        log.info("[pnl] {}", line);
                    }
                    for (String line : latency.summaryLines()) {
                        log.info("[latency] {}", line);
                    }
                    if (++cycle[0] % 6 == 0) {
                        for (String line : latency.cumulativeSummaryLines()) {
                            log.info("[latency-cum] {}", line);
                        }
                        // Periodic report snapshot: on Windows a background
                        // process usually dies by hard kill (no shutdown
                        // hook), so the report must not exist only at exit.
                        latency.writeReport(Path.of(config.reportsDir).resolve("latency-latest.txt"));
                    }
                } catch (Exception e) {
                    log.error("Stats cycle failed", e);
                }
            }, config.statsLogIntervalMs, config.statsLogIntervalMs, TimeUnit.MILLISECONDS);

            CountDownLatch stopped = new CountDownLatch(1);
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                log.info("Shutdown hook triggered");
                try {
                    stats.shutdownNow();
                } catch (Exception ignored) { }
                try {
                    tailer.shutdown();
                    tailer.join(3_000);
                } catch (Exception ignored) { }
                try {
                    disruptor.shutdown();
                } catch (Exception ignored) { }
                try {
                    orderWriter.close();
                } catch (Exception ignored) { }
                try {
                    simFill.close();
                } catch (Exception ignored) { }
                try {
                    auditHandler.close();
                } catch (Exception ignored) { }
                // Stats thread and pipeline are stopped — safe to drain the
                // recorders and write the whole-run report.
                try {
                    Path report = Path.of(config.reportsDir).resolve("latency-"
                            + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"))
                            + ".txt");
                    latency.writeReport(report);
                    log.info("Latency report written: {}", report.toAbsolutePath());
                } catch (Exception e) {
                    log.error("Failed to write latency report", e);
                }
                stopped.countDown();
            }, "shutdown-hook"));

            tailer.start();
            log.info("Strategy+Execution started. Press Ctrl-C to shut down.");
            stopped.await();
        } catch (Exception e) {
            log.error("Fatal startup error", e);
            System.exit(1);
        }
    }
}
