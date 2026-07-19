package com.yexl.trading.strategy.handlers;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Pipeline stage 2 — pretrade risk check against local, config-hardcoded
 * limits. Structurally separate from order placement (the split is the
 * point, even in a stub — this is the seam where real limit sync from the
 * authoritative C# service lands later).
 *
 * <p>Checks: (1) rolling orders-per-minute cap; (2) max absolute net
 * position per product, updated <b>optimistically at approval time</b> —
 * this process must not wait for the fill to round-trip through the async
 * reconciliation path to know it just changed its own exposure.
 */
public final class RiskCheckHandler implements EventHandler<StrategyEvent> {

    private static final Logger log = LoggerFactory.getLogger(RiskCheckHandler.class);

    private final StrategyConfig config;
    private final double orderQty;
    /** stream mode: "now" is the current doc's recvTs — see StrategyConfig.clockMode. */
    private final boolean streamClock;

    /** Rolling window of approval timestamps (epoch nanos) for the per-minute cap. */
    private final Deque<Long> approvalTimes = new ArrayDeque<>();
    /** Optimistic net position per product, in units of orderQty trades. */
    private final Map<String, Double> netPosition = new HashMap<>();

    private final AtomicLong approved = new AtomicLong();
    private final AtomicLong rejected = new AtomicLong();

    public RiskCheckHandler(StrategyConfig config) {
        this.config = config;
        this.orderQty = Double.parseDouble(config.orderQty);
        this.streamClock = "stream".equals(config.clockMode);
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        if (event.signal == StrategyEvent.SIGNAL_NONE) {
            return;
        }
        try {
            String product = event.delta.productId;
            long nowNanos = streamClock
                    ? event.delta.recvTsEpochNanos
                    : System.currentTimeMillis() * 1_000_000L;

            while (!approvalTimes.isEmpty() && nowNanos - approvalTimes.peekFirst() > 60_000_000_000L) {
                approvalTimes.pollFirst();
            }
            if (approvalTimes.size() >= config.riskMaxOrdersPerMinute) {
                reject(event, "orders-per-minute cap (" + config.riskMaxOrdersPerMinute + ")");
                return;
            }

            double pos = netPosition.getOrDefault(product, 0.0);
            double newPos = pos + event.signal * orderQty;
            if (Math.abs(newPos) > config.riskMaxAbsPosition) {
                reject(event, String.format("position cap (|%.6f| > %.6f)", newPos, config.riskMaxAbsPosition));
                return;
            }

            netPosition.put(product, newPos);
            approvalTimes.addLast(nowNanos);
            event.riskApproved = true;
            approved.incrementAndGet();
        } finally {
            event.riskNanos = System.nanoTime();
        }
    }

    private void reject(StrategyEvent event, String reason) {
        event.riskApproved = false;
        event.riskRejectReason = reason;
        rejected.incrementAndGet();
        log.warn("[{}] signal REJECTED: {}", event.delta.productId, reason);
    }

    public long approvedCount() {
        return approved.get();
    }

    public long rejectedCount() {
        return rejected.get();
    }
}
