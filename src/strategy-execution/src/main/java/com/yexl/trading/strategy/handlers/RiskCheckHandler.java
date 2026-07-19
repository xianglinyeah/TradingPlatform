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
 * <p>Checks (all limits USD notional, per-product overridable — the
 * institutional shape: notional is comparable across products): (1) rolling
 * orders-per-minute caps, process-wide then per product; (2) max absolute
 * net exposure per product at touch price, updated <b>optimistically at
 * approval time</b> — this process must not wait for the fill to round-trip
 * through the async reconciliation path to know it just changed its own
 * exposure.
 */
public final class RiskCheckHandler implements EventHandler<StrategyEvent> {

    private static final Logger log = LoggerFactory.getLogger(RiskCheckHandler.class);

    private final StrategyConfig config;
    /** stream mode: "now" is the current doc's recvTs — see StrategyConfig.clockMode. */
    private final boolean streamClock;

    /** Rolling windows of approval timestamps (epoch nanos): process-wide + per product. */
    private final Deque<Long> globalApprovals = new ArrayDeque<>();
    private final Map<String, Deque<Long>> productApprovals = new HashMap<>();
    /** Optimistic net position per product, base-currency units. */
    private final Map<String, Double> netPosition = new HashMap<>();

    private final AtomicLong approved = new AtomicLong();
    private final AtomicLong rejected = new AtomicLong();

    public RiskCheckHandler(StrategyConfig config) {
        this.config = config;
        this.streamClock = "stream".equals(config.clockMode);
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        if (event.signal == StrategyEvent.SIGNAL_NONE) {
            return;
        }
        try {
            String product = event.delta.productId;
            // venue|product key, consistent with SimFillHandler: product ids
            // alone are only unique per venue by convention, not construction.
            String key = event.delta.venue + '|' + product;
            long nowNanos = streamClock
                    ? event.delta.recvTsEpochNanos
                    : System.currentTimeMillis() * 1_000_000L;

            prune(globalApprovals, nowNanos);
            Deque<Long> perProduct = productApprovals.computeIfAbsent(key, k -> new ArrayDeque<>());
            prune(perProduct, nowNanos);
            if (globalApprovals.size() >= config.riskMaxOrdersPerMinute) {
                reject(event, "orders-per-minute cap (" + config.riskMaxOrdersPerMinute + ")");
                return;
            }
            if (perProduct.size() >= config.riskMaxOrdersPerMinutePerProduct) {
                reject(event, "per-product orders-per-minute cap ("
                        + config.riskMaxOrdersPerMinutePerProduct + ")");
                return;
            }

            double price = Double.parseDouble(event.touchPrice);
            double pos = netPosition.getOrDefault(key, 0.0);
            double newPos = pos + event.signal * event.orderQty.doubleValue();
            double newNotional = Math.abs(newPos) * price;
            double cap = config.riskMaxAbsNotionalUsd(product);
            if (newNotional > cap) {
                reject(event, String.format("notional cap ($%.2f > $%.2f)", newNotional, cap));
                return;
            }

            netPosition.put(key, newPos);
            globalApprovals.addLast(nowNanos);
            perProduct.addLast(nowNanos);
            event.riskApproved = true;
            approved.incrementAndGet();
        } finally {
            event.riskNanos = System.nanoTime();
        }
    }

    private static void prune(Deque<Long> window, long nowNanos) {
        while (!window.isEmpty() && nowNanos - window.peekFirst() > 60_000_000_000L) {
            window.pollFirst();
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
