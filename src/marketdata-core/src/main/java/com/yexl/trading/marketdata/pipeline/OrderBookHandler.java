package com.yexl.trading.marketdata.pipeline;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.marketdata.metrics.LatencyTracker;
import com.yexl.trading.marketdata.model.BookState;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.EventMessageType;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.book.OrderBook;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Disruptor Stage 3 — applies parsed updates to {@link OrderBook}s on Thread 3.
 *
 * <p>Routing within a single event:
 * <ul>
 *   <li>Updates flagged {@code isSnapshot == true} are grouped by product and
 *       applied via {@link OrderBook#applySnapshot(List)} (which clears
 *       first).</li>
 *   <li>Remaining updates are applied incrementally via
 *       {@link OrderBook#applyUpdate(BookUpdate)}.</li>
 * </ul>
 *
 * <p>Snapshot batches are applied first so that any same-frame incremental
 * updates land on the freshly-snapshotted book.
 */
public final class OrderBookHandler implements EventHandler<MarketDataEvent> {

    private static final Logger log = LoggerFactory.getLogger(OrderBookHandler.class);

    private final OrderBookManager manager;
    private final RecoveryManager recoveryManager;
    private final LatencyTracker latencyTracker;
    /** Optional venue integrity hook (e.g. OKX checksum); null for venues without one. */
    private final BookIntegrityCheck integrityCheck;

    // Reused scratch structures. OrderBookHandler is single-threaded (Disruptor
    // guarantees it), so these don't need synchronization.
    private final Map<String, List<BookUpdate>> snapshotBatches = new HashMap<>();
    private final List<BookUpdate> incrementalList = new ArrayList<>();

    public OrderBookHandler(OrderBookManager manager, RecoveryManager recoveryManager,
                            LatencyTracker latencyTracker) {
        this(manager, recoveryManager, latencyTracker, null);
    }

    public OrderBookHandler(OrderBookManager manager, RecoveryManager recoveryManager,
                            LatencyTracker latencyTracker, BookIntegrityCheck integrityCheck) {
        this.manager = manager;
        this.recoveryManager = recoveryManager;
        this.latencyTracker = latencyTracker;
        this.integrityCheck = integrityCheck;
    }

    @Override
    public void onEvent(MarketDataEvent event, long sequence, boolean endOfBatch) {
        switch (event.messageType) {
            case SNAPSHOT, UPDATE -> {
                handleBookChanges(event);
                // Latency is recorded for L2 events only — heartbeats and
                // subscription acks would dilute the distribution.
                event.bookAppliedNanos = System.nanoTime();
                latencyTracker.record(event);
                // After the stamp so the bookApplied segment stays pure apply
                // cost; the check's cost still shows in the publish segment.
                if (integrityCheck != null) {
                    integrityCheck.afterApply(event, manager);
                }
            }
            case HEARTBEAT -> {
                recoveryManager.onHeartbeat();
                if (log.isTraceEnabled()) {
                    log.trace("Heartbeat counter={} seq={}", event.heartbeatCounter, event.sequenceNum);
                }
            }
            case SUBSCRIBED, UNSUBSCRIBED -> log.debug("Subscription ack");
            case ERROR -> log.warn("Skipping ERROR event on order book");
            default -> { /* UNKNOWN: no-op */ }
        }
    }

    private void handleBookChanges(MarketDataEvent event) {
        BookUpdate[] updates = event.updates;
        if (updates == null || event.updateCount == 0) {
            return;
        }

        snapshotBatches.clear();
        incrementalList.clear();

        for (int i = 0; i < event.updateCount; i++) {
            BookUpdate u = updates[i];
            if (u == null || u.productId == null) {
                log.warn("Skipping malformed BookUpdate at index {} (seq={}): {}",
                        i, event.sequenceNum, u);
                continue;
            }
            if (u.isSnapshot) {
                snapshotBatches
                        .computeIfAbsent(u.productId, k -> new ArrayList<>())
                        .add(u);
            } else {
                incrementalList.add(u);
            }
        }

        // Snapshots first.
        for (Map.Entry<String, List<BookUpdate>> entry : snapshotBatches.entrySet()) {
            OrderBook book = manager.getOrCreate(entry.getKey());
            BookState before = book.state();
            book.applySnapshot(entry.getValue());
            if (before == BookState.STALE) {
                recoveryManager.onRecovered(entry.getKey());
            }
        }
        // Then incremental updates.
        for (BookUpdate u : incrementalList) {
            OrderBook book = manager.getOrCreate(u.productId);
            book.applyUpdate(u);
        }
    }
}
