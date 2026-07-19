package com.yexl.trading.marketdata.book;

import com.yexl.trading.marketdata.wire.MdDelta;

import java.math.BigDecimal;
import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;

/**
 * Strategy-side L2 replica for one product, rebuilt purely from the
 * normalized delta stream. Single-threaded (owned by the SignalHandler
 * thread) — no locking.
 *
 * <p>Deliberately minimal: apply-snapshot/apply-delta with the same
 * semantics as the publisher's book (qty=0 removes a level, otherwise the
 * quantity is the new absolute total), plus the top-N aggregations the
 * imbalance signal needs. This is the "consumer maintains its own replica
 * from deltas" half of the queue contract.
 */
public final class TopBook {

    private final TreeMap<BigDecimal, BigDecimal> bids = new TreeMap<>(Collections.reverseOrder());
    private final TreeMap<BigDecimal, BigDecimal> asks = new TreeMap<>();

    /** False until the first snapshot document has been applied. */
    private boolean snapshotSeen;

    /** Apply one delta document. Snapshot docs clear and reload. */
    public void apply(MdDelta d) {
        if (d.snapshot) {
            bids.clear();
            asks.clear();
            snapshotSeen = true;
        } else if (!snapshotSeen) {
            // Deltas before any snapshot would build a hole-riddled book;
            // ignore until a snapshot arrives (mid-stream join case).
            return;
        }
        for (int i = 0; i < d.levelCount; i++) {
            TreeMap<BigDecimal, BigDecimal> side =
                    d.sides[i] == MdDelta.SIDE_BID ? bids : asks;
            BigDecimal price = new BigDecimal(d.prices[i]);
            BigDecimal qty = new BigDecimal(d.qtys[i]);
            if (qty.signum() == 0) {
                side.remove(price);
            } else {
                side.put(price, qty);
            }
        }
    }

    public boolean ready(int minLevels) {
        return snapshotSeen && bids.size() >= minLevels && asks.size() >= minLevels;
    }

    public BigDecimal bestBid() {
        return bids.isEmpty() ? null : bids.firstKey();
    }

    public BigDecimal bestAsk() {
        return asks.isEmpty() ? null : asks.firstKey();
    }

    public double topNBidQty(int n) {
        return topNQty(bids, n);
    }

    public double topNAskQty(int n) {
        return topNQty(asks, n);
    }

    /** Mid price, or null while either side is empty. */
    public BigDecimal mid() {
        if (bids.isEmpty() || asks.isEmpty()) {
            return null;
        }
        return bids.firstKey().add(asks.firstKey())
                .divide(BigDecimal.valueOf(2), java.math.MathContext.DECIMAL64);
    }

    /** Result of walking one side of the book: volume-weighted price of what filled. */
    public record WalkResult(BigDecimal avgPrice, BigDecimal filledQty) { }

    /**
     * Walk the opposite side for a marketable order: BUY consumes asks from
     * the touch down the book, SELL consumes bids. {@code haircut} scales
     * every level's displayed quantity (you never get all of what you see —
     * others race you for it). IOC semantics: fills what the (haircut) book
     * holds, the rest is the caller's to treat as canceled. Returns null if
     * nothing filled.
     */
    public WalkResult walk(boolean buy, BigDecimal qty, BigDecimal haircut) {
        TreeMap<BigDecimal, BigDecimal> side = buy ? asks : bids;
        BigDecimal remaining = qty;
        BigDecimal notional = BigDecimal.ZERO;
        for (Map.Entry<BigDecimal, BigDecimal> level : side.entrySet()) {
            BigDecimal avail = level.getValue().multiply(haircut);
            if (avail.signum() <= 0) {
                continue;
            }
            BigDecimal take = remaining.min(avail);
            notional = notional.add(take.multiply(level.getKey()));
            remaining = remaining.subtract(take);
            if (remaining.signum() == 0) {
                break;
            }
        }
        BigDecimal filled = qty.subtract(remaining);
        if (filled.signum() == 0) {
            return null;
        }
        return new WalkResult(notional.divide(filled, java.math.MathContext.DECIMAL64), filled);
    }

    private static double topNQty(TreeMap<BigDecimal, BigDecimal> side, int n) {
        double sum = 0;
        int i = 0;
        for (Map.Entry<BigDecimal, BigDecimal> e : side.entrySet()) {
            if (i++ >= n) {
                break;
            }
            sum += e.getValue().doubleValue();
        }
        return sum;
    }
}
