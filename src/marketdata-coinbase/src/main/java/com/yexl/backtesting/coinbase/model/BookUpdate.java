package com.yexl.backtesting.coinbase.model;

import java.math.BigDecimal;

/**
 * A single price-level change. Mutable and intended to be reused in-place by
 * the Disruptor parse handler — never {@code new} inside the hot path.
 *
 * <p>A {@code qty} of {@link BigDecimal#ZERO} (per {@link BigDecimal#signum})
 * indicates the price level has been exhausted and should be removed from the
 * book.
 */
public final class BookUpdate {

    public Side side;
    public String productId;
    public BigDecimal price;
    public BigDecimal qty;
    public long eventTimeNanos;

    /**
     * Set by the parse handler when the parent Coinbase event had
     * {@code type == "snapshot"}. OrderBookHandler uses this to route the
     * update to {@code applySnapshot} (clearing-then-adding) instead of
     * {@code applyUpdate} (incremental).
     */
    public boolean isSnapshot;

    public void set(Side side, String productId, BigDecimal price, BigDecimal qty,
                    long eventTimeNanos, boolean isSnapshot) {
        this.side = side;
        this.productId = productId;
        this.price = price;
        this.qty = qty;
        this.eventTimeNanos = eventTimeNanos;
        this.isSnapshot = isSnapshot;
    }

    public void clear() {
        this.side = null;
        this.productId = null;
        this.price = null;
        this.qty = null;
        this.eventTimeNanos = 0L;
        this.isSnapshot = false;
    }

    @Override
    public String toString() {
        return "BookUpdate{" +
                "side=" + side +
                ", productId='" + productId + '\'' +
                ", price=" + price +
                ", qty=" + qty +
                ", isSnapshot=" + isSnapshot +
                '}';
    }
}
