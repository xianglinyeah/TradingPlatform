package com.yexl.trading.marketdata.wire;

import java.util.Arrays;

/**
 * Mutable, reusable carrier for one normalized market-data document —
 * the single in-memory representation on both sides of the queue
 * (producer fills it before {@link MdWireCodec#write}, consumer receives it
 * from {@link MdWireCodec#read}).
 *
 * <p>Level arrays grow on demand and are never shrunk; {@link #levelCount}
 * bounds the valid entries. Prices/quantities are decimal strings — exact,
 * venue-agnostic; each side chooses its own numeric representation.
 */
public final class MdDelta {

    public static final byte SIDE_BID = 0;
    public static final byte SIDE_ASK = 1;

    /** Schema version read from / written to the wire. */
    public int schemaVersion;
    public String venue;
    public String productId;
    /** True = downstream must clear its book for this product and reload from this doc. */
    public boolean snapshot;
    /** Publisher-assigned dense sequence — THE continuity check for consumers. */
    public long pseq;
    /** Venue sequence of the source frame (informational; NOT dense in the queue). */
    public long venueSeq;
    /** Exchange frame timestamp, epoch nanos (0 if absent). */
    public long exchTsEpochNanos;
    /** WS receive time at the publisher, epoch nanos. */
    public long recvTsEpochNanos;
    /** Publish time, epoch nanos. */
    public long pubTsEpochNanos;

    public int levelCount;
    public byte[] sides = new byte[64];
    public String[] prices = new String[64];
    public String[] qtys = new String[64];

    /** Ensure capacity for {@code n} levels and set {@link #levelCount}. */
    public void prepareLevels(int n) {
        if (sides.length < n) {
            int cap = Math.max(n, sides.length * 2);
            sides = Arrays.copyOf(sides, cap);
            prices = Arrays.copyOf(prices, cap);
            qtys = Arrays.copyOf(qtys, cap);
        }
        levelCount = n;
    }

    public void setLevel(int i, byte side, String price, String qty) {
        sides[i] = side;
        prices[i] = price;
        qtys[i] = qty;
    }

    public void copyFrom(MdDelta o) {
        schemaVersion = o.schemaVersion;
        venue = o.venue;
        productId = o.productId;
        snapshot = o.snapshot;
        pseq = o.pseq;
        venueSeq = o.venueSeq;
        exchTsEpochNanos = o.exchTsEpochNanos;
        recvTsEpochNanos = o.recvTsEpochNanos;
        pubTsEpochNanos = o.pubTsEpochNanos;
        prepareLevels(o.levelCount);
        System.arraycopy(o.sides, 0, sides, 0, o.levelCount);
        System.arraycopy(o.prices, 0, prices, 0, o.levelCount);
        System.arraycopy(o.qtys, 0, qtys, 0, o.levelCount);
    }

    public void clear() {
        schemaVersion = 0;
        venue = null;
        productId = null;
        snapshot = false;
        pseq = 0L;
        venueSeq = 0L;
        exchTsEpochNanos = 0L;
        recvTsEpochNanos = 0L;
        pubTsEpochNanos = 0L;
        levelCount = 0;
    }
}
