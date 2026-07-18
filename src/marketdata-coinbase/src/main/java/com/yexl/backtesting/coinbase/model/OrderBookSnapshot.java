package com.yexl.backtesting.coinbase.model;

import java.util.List;

/**
 * Immutable deep snapshot of an order book at a point in time.
 *
 * <p>{@code bids} are ordered high-to-low (best bid first),
 * {@code asks} are ordered low-to-high (best ask first).
 */
public record OrderBookSnapshot(String productId,
                                List<PriceLevel> bids,
                                List<PriceLevel> asks,
                                long captureNanos) {
}
