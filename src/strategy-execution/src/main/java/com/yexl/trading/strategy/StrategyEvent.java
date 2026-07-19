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

    // ---- SignalHandler outputs ----
    public int signal;
    public double imbalance;
    /** Touch price the order would cross at (best ask for BUY, best bid for SELL), decimal string. */
    public String touchPrice;
    public long signalNanos;

    // ---- RiskCheckHandler outputs ----
    public boolean riskApproved;
    public String riskRejectReason;
    public long riskNanos;

    // ---- OrderWriterHandler output ----
    public long placedNanos;
    /** Order id assigned when the order JSONL line is written; -1 = no order. */
    public long orderId;

    public void reset() {
        delta.clear();
        consumeNanos = 0L;
        consumeEpochNanos = 0L;
        catchup = false;
        signal = SIGNAL_NONE;
        imbalance = 0.0;
        touchPrice = null;
        signalNanos = 0L;
        riskApproved = false;
        riskRejectReason = null;
        riskNanos = 0L;
        placedNanos = 0L;
        orderId = -1L;
    }

    public static final EventFactory<StrategyEvent> FACTORY = StrategyEvent::new;
}
