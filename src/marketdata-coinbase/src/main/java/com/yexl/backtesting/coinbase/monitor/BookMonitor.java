package com.yexl.backtesting.coinbase.monitor;

import com.yexl.backtesting.coinbase.model.OrderBookSnapshot;
import com.yexl.backtesting.coinbase.model.PriceLevel;
import com.yexl.backtesting.coinbase.orderbook.OrderBook;
import com.yexl.backtesting.coinbase.orderbook.OrderBookManager;
import com.yexl.backtesting.coinbase.recovery.RecoveryManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Periodically snapshots every known order book and logs top-of-book plus a
 * sanity check (best bid &lt; best ask).
 *
 * <p>Runs on its own single-threaded scheduler — independent of the Disruptor
 * hot path, mirroring the design intent of Phase 3's Kafka publisher (which
 * will share this "consume AtomicReference/snapshot off the hot path"
 * pattern).
 */
public final class BookMonitor implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(BookMonitor.class);

    private final OrderBookManager manager;
    private final List<String> productIds;
    private final int depth;
    private final long intervalMs;
    private final RecoveryManager recoveryManager;
    private final ScheduledExecutorService scheduler;

    // Diagnostic counters (logged each cycle).
    private final AtomicLong sanityFailures = new AtomicLong();

    public BookMonitor(OrderBookManager manager, List<String> productIds,
                       int depth, long intervalMs, RecoveryManager recoveryManager) {
        this.manager = manager;
        this.productIds = productIds;
        this.depth = depth;
        this.intervalMs = intervalMs;
        this.recoveryManager = recoveryManager;
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "book-monitor");
            t.setDaemon(true);
            return t;
        });
    }

    public void start() {
        scheduler.scheduleAtFixedRate(
                this::snapshotAll,
                /* initialDelay */ intervalMs,
                /* period */ intervalMs,
                TimeUnit.MILLISECONDS
        );
        log.info("BookMonitor started (interval={}ms, depth={}, products={})",
                intervalMs, depth, productIds);
    }

    private void snapshotAll() {
        try {
            for (String pid : productIds) {
                OrderBook book = manager.get(pid);
                if (book == null) {
                    log.info("[{}] No OrderBook created yet", pid);
                    continue;
                }
                if (!book.isSnapshotInitialized()) {
                    log.info("[{}] Awaiting first snapshot...", pid);
                    continue;
                }

                OrderBookSnapshot snap = book.snapshot(depth);
                boolean ok = book.sanityCheck();
                if (!ok) {
                    long count = sanityFailures.incrementAndGet();
                    log.error("[{}] SANITY CHECK FAILED: best_bid >= best_ask " +
                            "(failure #{} for this process)", pid, count);
                }

                PriceLevel bestBid = firstOrNull(snap.bids());
                PriceLevel bestAsk = firstOrNull(snap.asks());
                String spread = (bestBid != null && bestAsk != null)
                        ? bestAsk.price().subtract(bestBid.price()).toPlainString()
                        : "-";
                log.info("[{}] state={} | bid={} | ask={} | spread={} | bidLvls={} askLvls={}",
                        pid,
                        book.state(),
                        formatLevel(bestBid),
                        formatLevel(bestAsk),
                        spread,
                        snap.bids().size(),
                        snap.asks().size());
            }
            log.info("[recovery] sequenceGaps={} disconnects={} heartbeatTimeouts={} " +
                    "staleTransitions={} recovered={} reconnectAttempts={} sanityFailures={}",
                    recoveryManager.sequenceGapCount(),
                    recoveryManager.disconnectCount(),
                    recoveryManager.heartbeatTimeoutCount(),
                    recoveryManager.staleTransitionCount(),
                    recoveryManager.recoveredCount(),
                    recoveryManager.reconnectAttemptCount(),
                    sanityFailures.get());
        } catch (Exception e) {
            log.error("BookMonitor cycle failed", e);
        }
    }

    private static PriceLevel firstOrNull(List<PriceLevel> l) {
        return (l == null || l.isEmpty()) ? null : l.get(0);
    }

    private static String formatLevel(PriceLevel lvl) {
        return lvl == null ? "-" : (lvl.price().toPlainString() + " x " + lvl.qty().toPlainString());
    }

    @Override
    public void close() {
        scheduler.shutdownNow();
        log.info("BookMonitor stopped (total sanityFailures={})", sanityFailures.get());
    }
}
