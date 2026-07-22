package com.yexl.trading.strategy;

import com.lmax.disruptor.EventFactory;
import com.yexl.trading.marketdata.wire.MdDelta;

/**
 * Disruptor event for the Strategy+Execution pipeline. One market-data
 * document = one event.
 *
 * <p>Threading: the tailer thread copies the decoded {@link MdDelta} in and
 * stamps the consume times; SignalHandler fills the signal fields;
 * RiskCheckHandler the risk fields; OrderWriterHandler stamps placement.
 */
public final class StrategyEvent {

    public static final int SIGNAL_NONE = 0;
    public static final int SIGNAL_BUY = 1;
    public static final int SIGNAL_SELL = -1;

    /** Embedded copy of the consumed document (arrays reused across events). */
    public final MdDelta delta = new MdDelta();

    /** {@link System#nanoTime()} when the tailer thread finished decoding. */
    public long consumeNanos;
    /** Wall-clock epoch nanos at the same moment (comparable with delta.pubTsEpochNanos). */
    public long consumeEpochNanos;
    /** True until the tailer reaches the live queue tail — startup replay, not live flow. */
    public boolean catchup;
    /** Chronicle Queue index of this document (single-queue mode only; -1 in multi-queue/arb mode) —
     * lets a periodic checkpoint record exactly where to resume a restart without full replay. */
    public long queueIndex = -1L;

    // ---- SignalHandler outputs ----
    public int signal;
    public double imbalance;
    /** Touch price the order would cross at (best ask for BUY, best bid for SELL), decimal string. */
    public String touchPrice;
    /** Base-currency order qty: per-product USD notional / touch price. */
    public java.math.BigDecimal orderQty;
    public long signalNanos;

    // ---- RiskCheckHandler outputs ----
    public boolean riskApproved;
    public String riskRejectReason;
    public long riskNanos;

    // ---- OrderWriterHandler output ----
    public long placedNanos;
    /** Order id assigned when the order JSONL line is written; -1 = no order. */
    public long orderId;

    // ---- Arb mode (strategy.mode=arb): one signal = two legs ----
    /** True when ArbSignalHandler populated both legs. */
    public boolean arbSignal;
    public String arbSymbol;
    /** Spread deviation from its EMA at signal time, bps of mid. */
    public double arbDevBps;
    /** EMA of the cross-venue spread at signal time, bps of mid. */
    public double arbEmaBps;
    public final Leg arbBuyLeg = new Leg();
    public final Leg arbSellLeg = new Leg();

    /** One venue-specific leg of an arb order pair. */
    public static final class Leg {
        public String venue;
        public String productId;
        public java.math.BigDecimal qty;
        /** Touch price this leg would cross at (ask for the buy leg, bid for the sell leg). */
        public String touchPrice;
        /** Order id assigned by OrderWriterHandler; -1 = not placed. */
        public long orderId = -1L;

        void reset() {
            venue = null;
            productId = null;
            qty = null;
            touchPrice = null;
            orderId = -1L;
        }
    }

    public void reset() {
        delta.clear();
        consumeNanos = 0L;
        consumeEpochNanos = 0L;
        catchup = false;
        queueIndex = -1L;
        signal = SIGNAL_NONE;
        imbalance = 0.0;
        touchPrice = null;
        orderQty = null;
        signalNanos = 0L;
        riskApproved = false;
        riskRejectReason = null;
        riskNanos = 0L;
        placedNanos = 0L;
        orderId = -1L;
        arbSignal = false;
        arbSymbol = null;
        arbDevBps = 0.0;
        arbEmaBps = 0.0;
        arbBuyLeg.reset();
        arbSellLeg.reset();
    }

    public static final EventFactory<StrategyEvent> FACTORY = StrategyEvent::new;
}
