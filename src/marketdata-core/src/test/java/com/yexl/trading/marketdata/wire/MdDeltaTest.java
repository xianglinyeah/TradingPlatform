package com.yexl.trading.marketdata.wire;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MdDeltaTest {

    @Test
    void prepareLevelsGrowsArraysBeyondInitialCapacity() {
        MdDelta d = new MdDelta();
        int initialCap = d.sides.length;

        d.prepareLevels(initialCap + 10);

        assertEquals(initialCap + 10, d.levelCount);
        assertTrue(d.sides.length >= initialCap + 10);
        assertTrue(d.prices.length >= initialCap + 10);
        assertTrue(d.qtys.length >= initialCap + 10);
    }

    @Test
    void prepareLevelsWithinCapacityJustSetsCount() {
        MdDelta d = new MdDelta();
        int cap = d.sides.length;

        d.prepareLevels(3);

        assertEquals(3, d.levelCount);
        assertEquals(cap, d.sides.length);
    }

    @Test
    void copyFromDuplicatesAllFieldsAndLevels() {
        MdDelta src = new MdDelta();
        src.schemaVersion = 1;
        src.venue = "OKX";
        src.productId = "BTC-USDT";
        src.snapshot = true;
        src.pseq = 7L;
        src.venueSeq = 8L;
        src.exchTsEpochNanos = 1L;
        src.recvTsEpochNanos = 2L;
        src.pubTsEpochNanos = 3L;
        src.prepareLevels(2);
        src.setLevel(0, MdDelta.SIDE_BID, "10", "1");
        src.setLevel(1, MdDelta.SIDE_ASK, "11", "2");

        MdDelta dst = new MdDelta();
        dst.copyFrom(src);

        assertEquals(src.venue, dst.venue);
        assertEquals(src.productId, dst.productId);
        assertEquals(src.snapshot, dst.snapshot);
        assertEquals(src.pseq, dst.pseq);
        assertEquals(2, dst.levelCount);
        assertEquals("10", dst.prices[0]);
        assertEquals("11", dst.prices[1]);

        // Mutating the source afterward must not affect the copy.
        src.setLevel(0, MdDelta.SIDE_BID, "999", "999");
        assertEquals("10", dst.prices[0]);
    }

    @Test
    void clearResetsScalarFieldsButLeavesLevelArraysForReuse() {
        MdDelta d = new MdDelta();
        d.schemaVersion = 1;
        d.venue = "COINBASE";
        d.productId = "BTC-USD";
        d.snapshot = true;
        d.pseq = 5L;
        d.prepareLevels(1);
        d.setLevel(0, MdDelta.SIDE_BID, "1", "1");

        d.clear();

        assertEquals(0, d.schemaVersion);
        assertNull(d.venue);
        assertNull(d.productId);
        assertEquals(false, d.snapshot);
        assertEquals(0L, d.pseq);
        assertEquals(0, d.levelCount);
    }
}
