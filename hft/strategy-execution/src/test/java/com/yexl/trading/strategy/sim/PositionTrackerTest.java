package com.yexl.trading.strategy.sim;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PositionTrackerTest {

    @Test
    void sameDirectionFillsAverageCost() {
        PositionTracker t = new PositionTracker();

        t.onFill(1.0, 100.0, 0, false);
        t.onFill(1.0, 110.0, 0, false);

        assertEquals(2.0, t.position(), 1e-9);
        assertTrue(t.summary().contains("avgCost=105.00"));
    }

    @Test
    void opposingFillPartiallyClosesAndRealizesPnlAtOldAvgCost() {
        PositionTracker t = new PositionTracker();
        t.onFill(2.0, 100.0, 0, false);

        t.onFill(-1.0, 110.0, 0, false); // sells 1 of the 2 long units, +10 realized

        assertEquals(1.0, t.position(), 1e-9);
        assertEquals(10.0, t.realizedPnl(), 1e-9);
        assertTrue(t.summary().contains("avgCost=100.00")); // unchanged: still long, not flipped
    }

    @Test
    void closingExactlyToZeroResetsAvgCost() {
        PositionTracker t = new PositionTracker();
        t.onFill(1.0, 100.0, 0, false);

        t.onFill(-1.0, 120.0, 0, false);

        assertEquals(0.0, t.position(), 1e-9);
        assertEquals(20.0, t.realizedPnl(), 1e-9);
        assertTrue(t.summary().contains("avgCost=0.00"));
    }

    @Test
    void flippingThroughZeroOpensResidualAtTheFillPrice() {
        PositionTracker t = new PositionTracker();
        t.onFill(1.0, 100.0, 0, false); // long 1 @ 100

        t.onFill(-3.0, 90.0, 0, false); // sells 3: closes the 1 long (-10 realized), opens -2 short @ 90

        assertEquals(-2.0, t.position(), 1e-9);
        assertEquals(-10.0, t.realizedPnl(), 1e-9);
        assertTrue(t.summary().contains("avgCost=90.00"));
    }

    @Test
    void markMidFeedsUnrealizedPnlIntoSummary() {
        PositionTracker t = new PositionTracker();
        t.onFill(2.0, 100.0, 0, false);

        t.markMid(110.0);

        assertTrue(t.summary().contains("unrealized=20.0000"));
        assertTrue(t.summary().contains("net=20.0000"));
    }

    @Test
    void unrealizedIsZeroBeforeAnyMidIsMarked() {
        PositionTracker t = new PositionTracker();
        t.onFill(2.0, 100.0, 0, false);

        assertTrue(t.summary().contains("unrealized=0.0000"));
    }

    @Test
    void feesAndPartialFillsAreTrackedAndSubtractedFromNet() {
        PositionTracker t = new PositionTracker();

        t.onFill(1.0, 100.0, 5.0, true);

        assertTrue(t.summary().contains("fees=5.0000"));
        assertTrue(t.summary().contains("fills=1 partial=1"));
        assertTrue(t.summary().contains("net=-5.0000")); // no realized/unrealized yet, fees are pure drag
    }
}
