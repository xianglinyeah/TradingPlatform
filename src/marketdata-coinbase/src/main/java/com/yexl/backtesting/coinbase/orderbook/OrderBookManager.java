package com.yexl.backtesting.coinbase.orderbook;

import java.util.Collection;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Process-wide registry of {@link OrderBook}s by product ID.
 *
 * <p>Books are created lazily on first sighting of a product in an inbound
 * l2_data event. Phase 2's reconnect logic calls {@link #clearAllForResubscribe}
 * to invalidate every book before a fresh snapshot is expected.
 */
public final class OrderBookManager {

    private final ConcurrentHashMap<String, OrderBook> books = new ConcurrentHashMap<>();

    public OrderBook getOrCreate(String productId) {
        return books.computeIfAbsent(productId, OrderBook::new);
    }

    public OrderBook get(String productId) {
        return books.get(productId);
    }

    public Collection<OrderBook> all() {
        return books.values();
    }

    public void clearAllForResubscribe() {
        for (OrderBook book : books.values()) {
            book.clearForResubscribe();
        }
    }
}
