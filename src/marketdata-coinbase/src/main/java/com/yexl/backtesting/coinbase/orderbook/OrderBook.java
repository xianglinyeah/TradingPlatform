package com.yexl.backtesting.coinbase.orderbook;

import com.yexl.backtesting.coinbase.model.BookState;
import com.yexl.backtesting.coinbase.model.BookUpdate;
import com.yexl.backtesting.coinbase.model.OrderBookSnapshot;
import com.yexl.backtesting.coinbase.model.PriceLevel;
import com.yexl.backtesting.coinbase.model.Side;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.locks.ReadWriteLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;

/**
 * In-memory L2 order book for a single product.
 *
 * <p>Two {@link TreeMap}s keyed by {@link BigDecimal}:
 * <ul>
 *   <li>{@code bids} — descending order, so {@link TreeMap#firstEntry()}
 *       returns the best (highest) bid.</li>
 *   <li>{@code asks} — ascending (natural) order, so {@link TreeMap#firstEntry()}
 *       returns the best (lowest) ask.</li>
 * </ul>
 *
 * <p>BigDecimal is used as the key rather than {@code double} to avoid
 * floating-point comparison surprises on TreeMap lookups (e.g.
 * {@code "0.0001"} and {@code "0.00010"} parse to slightly different doubles
 * but compare equal as BigDecimal via {@link BigDecimal#compareTo}).
 *
 * <p>Thread safety: a {@link ReadWriteLock} guards all mutations and reads.
 * The Disruptor's OrderBookHandler is the only writer under normal
 * operation, but {@link com.yexl.backtesting.coinbase.monitor.BookMonitor}
 * reads concurrently from a scheduler thread.
 */
public final class OrderBook {

    private static final Logger log = LoggerFactory.getLogger(OrderBook.class);

    private final String productId;
    private final TreeMap<BigDecimal, BigDecimal> bids = new TreeMap<>(Collections.reverseOrder());
    private final TreeMap<BigDecimal, BigDecimal> asks = new TreeMap<>();
    private final ReadWriteLock lock = new ReentrantReadWriteLock();

    /**
     * Lifecycle state. {@code UNINITIALIZED} until the first snapshot lands;
     * {@code STALE} once a fault-detection trigger (sequence gap, disconnect,
     * heartbeat timeout) has flagged the book untrustworthy; {@code LIVE}
     * whenever a snapshot has been applied and no fault has been raised since.
     */
    private volatile BookState state = BookState.UNINITIALIZED;

    public OrderBook(String productId) {
        this.productId = productId;
    }

    public String productId() {
        return productId;
    }

    public BookState state() {
        return state;
    }

    public boolean isSnapshotInitialized() {
        return state != BookState.UNINITIALIZED;
    }

    /**
     * Mark this book untrustworthy. Called by the recovery pipeline in
     * response to a sequence gap, disconnect, or heartbeat timeout. Until the
     * next {@link #applySnapshot(List)}, {@link #applyUpdate(BookUpdate)}
     * silently drops incoming updates rather than layering them on top of a
     * known-bad book.
     */
    public void markStale() {
        lock.writeLock().lock();
        try {
            if (state != BookState.STALE) {
                state = BookState.STALE;
                log.warn("[{}] OrderBook marked STALE", productId);
            }
        } finally {
            lock.writeLock().unlock();
        }
    }

    /**
     * Clear both sides and populate from the given snapshot updates.
     * Transitions {@link #state} to {@code LIVE}.
     */
    public void applySnapshot(List<BookUpdate> snapshotUpdates) {
        lock.writeLock().lock();
        try {
            bids.clear();
            asks.clear();
            for (BookUpdate u : snapshotUpdates) {
                putNoLock(u);
            }
            BookState previous = state;
            state = BookState.LIVE;
            log.info("[{}] Snapshot applied: {} bid levels, {} ask levels (state {} -> LIVE)",
                    productId, bids.size(), asks.size(), previous);
        } finally {
            lock.writeLock().unlock();
        }
    }

    /**
     * Apply a single incremental update. No-op (with warning) unless the book
     * is currently {@code LIVE} — applying updates before the first snapshot,
     * or on top of a {@code STALE} book, would silently corrupt state.
     */
    public void applyUpdate(BookUpdate u) {
        if (state != BookState.LIVE) {
            log.warn("[{}] UPDATE received while state={}, dropping: price={} qty={}",
                    productId, state, u.price, u.qty);
            return;
        }
        lock.writeLock().lock();
        try {
            if (state != BookState.LIVE) {
                // Went STALE between the check above and acquiring the lock.
                return;
            }
            putNoLock(u);
        } finally {
            lock.writeLock().unlock();
        }
    }

    private void putNoLock(BookUpdate u) {
        TreeMap<BigDecimal, BigDecimal> book = (u.side == Side.BID) ? bids : asks;
        if (u.qty.signum() == 0) {
            book.remove(u.price);
        } else {
            // put-if-absent semantics are wrong here: Coinbase sends the new
            // *total* quantity at a price level, so overwrite unconditionally.
            book.put(u.price, u.qty);
        }
    }

    /**
     * Build a deep, immutable snapshot of the top {@code depth} levels on
     * each side.
     */
    public OrderBookSnapshot snapshot(int depth) {
        lock.readLock().lock();
        try {
            List<PriceLevel> bidLevels = takeTop(bids, depth);
            List<PriceLevel> askLevels = takeTop(asks, depth);
            return new OrderBookSnapshot(productId, bidLevels, askLevels, System.nanoTime());
        } finally {
            lock.readLock().unlock();
        }
    }

    private static List<PriceLevel> takeTop(TreeMap<BigDecimal, BigDecimal> book, int depth) {
        int n = Math.min(depth, book.size());
        if (n == 0) {
            return List.of();
        }
        List<PriceLevel> out = new ArrayList<>(n);
        int i = 0;
        for (Map.Entry<BigDecimal, BigDecimal> e : book.entrySet()) {
            if (i++ >= n) {
                break;
            }
            out.add(new PriceLevel(e.getKey(), e.getValue()));
        }
        return out;
    }

    /**
     * @return true if best bid &lt; best ask (or either side is empty).
     *         Violation indicates a corrupted book.
     */
    public boolean sanityCheck() {
        lock.readLock().lock();
        try {
            if (bids.isEmpty() || asks.isEmpty()) {
                return true;
            }
            BigDecimal bestBid = bids.firstKey();
            BigDecimal bestAsk = asks.firstKey();
            return bestBid.compareTo(bestAsk) < 0;
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Reset to pre-snapshot state and mark {@code STALE}. Called by the
     * recovery pipeline before a fresh snapshot is requested.
     */
    public void clearForResubscribe() {
        lock.writeLock().lock();
        try {
            bids.clear();
            asks.clear();
            state = BookState.STALE;
            log.info("[{}] OrderBook cleared for resubscribe", productId);
        } finally {
            lock.writeLock().unlock();
        }
    }

    public int bidDepth() {
        lock.readLock().lock();
        try {
            return bids.size();
        } finally {
            lock.readLock().unlock();
        }
    }

    public int askDepth() {
        lock.readLock().lock();
        try {
            return asks.size();
        } finally {
            lock.readLock().unlock();
        }
    }
}
