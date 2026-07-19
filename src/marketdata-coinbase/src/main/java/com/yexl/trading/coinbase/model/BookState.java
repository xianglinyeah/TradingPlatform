package com.yexl.trading.coinbase.model;

/**
 * Lifecycle state of an {@link com.yexl.trading.coinbase.orderbook.OrderBook}.
 *
 * <p>{@code STALE} means a fault-detection trigger (sequence gap, disconnect,
 * or heartbeat timeout) has marked the book untrustworthy pending a fresh
 * snapshot. Consumers must not trust a {@code STALE} book.
 */
public enum BookState {
    UNINITIALIZED,
    LIVE,
    STALE
}
