package com.yexl.trading.marketdata.book;

import com.yexl.trading.marketdata.wire.MdDelta;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TopBookTest {

    private static MdDelta doc(boolean snapshot, Object... levels) {
        MdDelta d = new MdDelta();
        d.snapshot = snapshot;
        int n = levels.length / 3;
        d.prepareLevels(n);
        for (int i = 0; i < n; i++) {
            byte side = (byte) levels[i * 3];
            String price = (String) levels[i * 3 + 1];
            String qty = (String) levels[i * 3 + 2];
            d.setLevel(i, side, price, qty);
        }
        return d;
    }

    @Test
    void notReadyUntilSnapshotSeenAndMinLevelsPresent() {
        TopBook book = new TopBook();
        assertFalse(book.ready(1));

        book.apply(doc(false, MdDelta.SIDE_BID, "100", "1")); // pre-snapshot delta ignored
        assertFalse(book.ready(1));

        book.apply(doc(true, MdDelta.SIDE_BID, "100", "1", MdDelta.SIDE_ASK, "101", "1"));
        assertTrue(book.ready(1));
        assertFalse(book.ready(2));
    }

    @Test
    void deltaAfterSnapshotUpdatesLevelsAndZeroQtyRemoves() {
        TopBook book = new TopBook();
        book.apply(doc(true, MdDelta.SIDE_BID, "100", "1", MdDelta.SIDE_ASK, "101", "1"));

        book.apply(doc(false, MdDelta.SIDE_BID, "100", "0"));

        assertNull(book.bestBid());
        assertEquals(0, new BigDecimal("101").compareTo(book.bestAsk()));
    }

    @Test
    void midIsNullUnlessBothSidesPresent() {
        TopBook book = new TopBook();
        assertNull(book.mid());

        book.apply(doc(true, MdDelta.SIDE_BID, "100", "1", MdDelta.SIDE_ASK, "102", "1"));
        assertEquals(0, new BigDecimal("101").compareTo(book.mid()));
    }

    @Test
    void topNQtySumsOnlyTopLevels() {
        TopBook book = new TopBook();
        book.apply(doc(true,
                MdDelta.SIDE_BID, "100", "1",
                MdDelta.SIDE_BID, "99", "2",
                MdDelta.SIDE_BID, "98", "4"));

        assertEquals(1.0, book.topNBidQty(1), 1e-9);
        assertEquals(3.0, book.topNBidQty(2), 1e-9);
        assertEquals(7.0, book.topNBidQty(10), 1e-9);
    }

    @Test
    void walkReturnsNullWhenNothingFills() {
        TopBook book = new TopBook();
        book.apply(doc(true, MdDelta.SIDE_ASK, "100", "1")); // no bid, but askable side is fine for a buy

        TopBook.WalkResult r = book.walk(false, new BigDecimal("1"), BigDecimal.ONE); // sell into empty bids
        assertNull(r);
    }

    @Test
    void walkFullyFillsAtSingleLevel() {
        TopBook book = new TopBook();
        book.apply(doc(true, MdDelta.SIDE_ASK, "100", "5"));

        TopBook.WalkResult r = book.walk(true, new BigDecimal("2"), BigDecimal.ONE);

        assertEquals(0, new BigDecimal("2").compareTo(r.filledQty()));
        assertEquals(0, new BigDecimal("100").compareTo(r.avgPrice()));
    }

    @Test
    void walkAcrossMultipleLevelsComputesVolumeWeightedAveragePrice() {
        TopBook book = new TopBook();
        book.apply(doc(true,
                MdDelta.SIDE_ASK, "100", "1",
                MdDelta.SIDE_ASK, "101", "1")); // best ask first, TreeMap orders naturally

        TopBook.WalkResult r = book.walk(true, new BigDecimal("2"), BigDecimal.ONE);

        assertEquals(0, new BigDecimal("2").compareTo(r.filledQty()));
        // (1*100 + 1*101) / 2 = 100.5
        assertEquals(0, new BigDecimal("100.5").compareTo(r.avgPrice()));
    }

    @Test
    void restoreSeedsBookAsIfSnapshotted() {
        TopBook source = new TopBook();
        source.apply(doc(true,
                MdDelta.SIDE_BID, "100", "1",
                MdDelta.SIDE_BID, "99", "2",
                MdDelta.SIDE_ASK, "101", "3"));

        TopBook restored = new TopBook();
        assertFalse(restored.ready(1));
        restored.restore(source.topBids(50), source.topAsks(50));

        assertTrue(restored.ready(1)); // only 1 ask level seeded above
        assertEquals(0, new BigDecimal("100").compareTo(restored.bestBid()));
        assertEquals(0, new BigDecimal("101").compareTo(restored.bestAsk()));
        assertEquals(3.0, restored.topNBidQty(2), 1e-9);

        // Live deltas apply normally post-restore -- no separate snapshot needed.
        restored.apply(doc(false, MdDelta.SIDE_BID, "100", "0"));
        assertEquals(0, new BigDecimal("99").compareTo(restored.bestBid()));
    }

    @Test
    void topLevelsRespectsMaxAndOrdering() {
        TopBook book = new TopBook();
        book.apply(doc(true,
                MdDelta.SIDE_BID, "100", "1",
                MdDelta.SIDE_BID, "99", "2",
                MdDelta.SIDE_BID, "98", "3"));

        var top2 = book.topBids(2);
        assertEquals(2, top2.size());
        assertEquals(0, new BigDecimal("100").compareTo(top2.get(0).price()));
        assertEquals(0, new BigDecimal("99").compareTo(top2.get(1).price()));
    }

    @Test
    void walkHaircutScalesAvailableQty() {
        TopBook book = new TopBook();
        book.apply(doc(true, MdDelta.SIDE_ASK, "100", "10"));

        TopBook.WalkResult r = book.walk(true, new BigDecimal("10"), new BigDecimal("0.5"));

        // only 5 of the displayed 10 is assumed available
        assertEquals(0, new BigDecimal("5").compareTo(r.filledQty()));
    }
}
