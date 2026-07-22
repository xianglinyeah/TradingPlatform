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
 * Pipeline stage 2, arb mode — pretrade risk for two-leg orders. Both legs
 * are checked first, then committed <b>atomically</b>: approving one leg of
 * an arb pair alone would be worse than rejecting both (naked directional
 * exposure is exactly what the strategy promises not to take).
 *
 * <p>Same limits as the single-venue handler, applied per leg: rolling
 * process-wide orders/min (an arb consumes 2), per venue|product orders/min,
 * and max absolute net exposure (USD notional at the leg's touch price),
 * positions updated optimistically at approval.
 */
public final class ArbRiskCheckHandler implements EventHandler<StrategyEvent> {

    private static final Logger log = LoggerFactory.getLogger(ArbRiskCheckHandler.class);

    private final StrategyConfig config;
    private final boolean streamClock;

    private final Deque<Long> globalApprovals = new ArrayDeque<>();
    /** Rolling approvals per venue|product. */
    private final Map<String, Deque<Long>> legApprovals = new HashMap<>();
    /** Optimistic net position per venue|product, base-currency units. */
    private final Map<String, Double> netPosition = new HashMap<>();

    private final AtomicLong approved = new AtomicLong();
    private final AtomicLong rejected = new AtomicLong();

    public ArbRiskCheckHandler(StrategyConfig config) {
        this.config = config;
        this.streamClock = "stream".equals(config.clockMode);
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        if (!event.arbSignal) {
            return;
        }
        try {
            long nowNanos = streamClock
                    ? event.delta.recvTsEpochNanos
                    : System.currentTimeMillis() * 1_000_000L;

            prune(globalApprovals, nowNanos);
            if (globalApprovals.size() + 2 > config.riskMaxOrdersPerMinute) {
                reject(event, "orders-per-minute cap (" + config.riskMaxOrdersPerMinute + ")");
                return;
            }

            String buyKey = legKey(event.arbBuyLeg);
            String sellKey = legKey(event.arbSellLeg);
            Deque<Long> buyWindow = legApprovals.computeIfAbsent(buyKey, k -> new ArrayDeque<>());
            Deque<Long> sellWindow = legApprovals.computeIfAbsent(sellKey, k -> new ArrayDeque<>());
            prune(buyWindow, nowNanos);
            prune(sellWindow, nowNanos);
            if (buyWindow.size() >= config.riskMaxOrdersPerMinutePerProduct
                    || sellWindow.size() >= config.riskMaxOrdersPerMinutePerProduct) {
                reject(event, "per-product orders-per-minute cap ("
                        + config.riskMaxOrdersPerMinutePerProduct + ")");
                return;
            }

            double qty = event.arbBuyLeg.qty.doubleValue();
            double newBuyPos = netPosition.getOrDefault(buyKey, 0.0) + qty;
            double newSellPos = netPosition.getOrDefault(sellKey, 0.0) - qty;
            double buyNotional = Math.abs(newBuyPos) * Double.parseDouble(event.arbBuyLeg.touchPrice);
            double sellNotional = Math.abs(newSellPos) * Double.parseDouble(event.arbSellLeg.touchPrice);
            double buyCap = config.riskMaxAbsNotionalUsd(event.arbBuyLeg.productId);
            double sellCap = config.riskMaxAbsNotionalUsd(event.arbSellLeg.productId);
            if (buyNotional > buyCap) {
                reject(event, String.format("notional cap %s ($%.2f > $%.2f)", buyKey, buyNotional, buyCap));
                return;
            }
            if (sellNotional > sellCap) {
                reject(event, String.format("notional cap %s ($%.2f > $%.2f)", sellKey, sellNotional, sellCap));
                return;
            }

            // All checks passed — commit both legs.
            netPosition.put(buyKey, newBuyPos);
            netPosition.put(sellKey, newSellPos);
            globalApprovals.addLast(nowNanos);
            globalApprovals.addLast(nowNanos);
            buyWindow.addLast(nowNanos);
            sellWindow.addLast(nowNanos);
            event.riskApproved = true;
            approved.incrementAndGet();
        } finally {
            event.riskNanos = System.nanoTime();
        }
    }

    private static String legKey(StrategyEvent.Leg leg) {
        return leg.venue + '|' + leg.productId;
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
        log.warn("[{}] arb signal REJECTED: {}", event.arbSymbol, reason);
    }

    public long approvedCount() {
        return approved.get();
    }

    public long rejectedCount() {
        return rejected.get();
    }
}
