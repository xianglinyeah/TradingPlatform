package com.yexl.backtesting.coinbase.model;

import com.lmax.disruptor.EventFactory;

/**
 * Disruptor event. One WebSocket frame = one event.
 *
 * <p>Threading model:
 * <ul>
 *   <li>Thread 1 (WS I/O) sets {@link #rawJson} and {@link #receiveTimeNanos}
 *       via an EventTranslator, then publishes.</li>
 *   <li>Thread 2 (ParseHandler) reads {@link #rawJson}, parses with Jackson,
 *       fills {@link #updates}, and nulls out {@link #rawJson}.</li>
 *   <li>Thread 3 (OrderBookHandler) reads {@link #updates} and applies them
 *       to the {@link com.yexl.backtesting.coinbase.orderbook.OrderBook}.</li>
 * </ul>
 *
 * <p>{@link #updates} is allocated lazily by the parse handler because a
 * Coinbase snapshot for a liquid product can carry thousands of price levels
 * while a typical incremental update carries only a handful. Pre-allocating
 * for the worst case across the entire ring buffer would waste gigabytes.
 * Phase 2 may introduce a thread-local pool to reduce per-message allocation.
 */
public final class MarketDataEvent {

    public EventMessageType messageType = EventMessageType.UNKNOWN;
    public ChannelType channel = ChannelType.UNKNOWN;

    /** Top-level {@code sequence_num} from the Coinbase frame. */
    public long sequenceNum;

    /** {@link System#nanoTime()} at the moment Thread 1 received the frame. */
    public long receiveTimeNanos;

    /** Top-level {@code timestamp} (ISO-8601 string) from the Coinbase frame. */
    public String exchangeTimestamp;

    /** Number of valid entries in {@link #updates}. */
    public int updateCount;

    /**
     * Lazily allocated array of price-level changes. Slot objects themselves
     * are also allocated lazily by the parse handler.
     */
    public BookUpdate[] updates;

    /** Heartbeat counter, only meaningful when {@link #messageType} == HEARTBEAT. */
    public long heartbeatCounter;

    /** Raw JSON text of the inbound WebSocket frame. Set by Thread 1, cleared by Thread 2. */
    public String rawJson;

    /** Reset all mutable fields between uses. Called by Thread 1 before publishing. */
    public void reset() {
        messageType = EventMessageType.UNKNOWN;
        channel = ChannelType.UNKNOWN;
        sequenceNum = 0L;
        receiveTimeNanos = 0L;
        exchangeTimestamp = null;
        updateCount = 0;
        heartbeatCounter = 0L;
        // Drop the reference to the previous batch so the array and its slot
        // objects can be reclaimed by young GC. Allocation cost is amortized
        // across the ring; for typical update messages it is a handful of
        // short-lived objects per frame.
        updates = null;
        rawJson = null;
    }

    public static final EventFactory<MarketDataEvent> FACTORY = MarketDataEvent::new;
}
