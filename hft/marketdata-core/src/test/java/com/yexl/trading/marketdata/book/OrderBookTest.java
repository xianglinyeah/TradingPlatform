package com.yexl.trading.marketdata.book;

import com.yexl.trading.marketdata.model.BookState;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.OrderBookSnapshot;
import com.yexl.trading.marketdata.model.Side;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OrderBookTest {

    private static BookUpdate update(Side side, String price, String qty) {
        BookUpdate u = new BookUpdate();
        u.set(side, "BTC-USD", new BigDecimal(price), new BigDecimal(qty), 0L, false);
        return u;
    }

    @Test
    void startsUninitializedAndRejectsUpdatesBeforeSnapshot() {
        OrderBook book = new OrderBook("BTC-USD");
        assertEquals(BookState.UNINITIALIZED, book.state());
        assertFalse(book.isSnapshotInitialized());

        book.applyUpdate(update(Side.BID, "100", "1"));

        assertEquals(0, book.bidDepth());
        assertEquals(BookState.UNINITIALIZED, book.state());
    }

    @Test
    void applySnapshotGoesLiveAndPopulatesBothSides() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(
                update(Side.BID, "100", "1"),
                update(Side.BID, "99", "2"),
                update(Side.ASK, "101", "1"),
                update(Side.ASK, "102", "3")
        ));

        assertEquals(BookState.LIVE, book.state());
        assertEquals(2, book.bidDepth());
        assertEquals(2, book.askDepth());
    }

    @Test
    void applyUpdateAddsAndOverwritesLevel() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(update(Side.BID, "100", "1")));

        book.applyUpdate(update(Side.BID, "100", "5"));
        OrderBookSnapshot snap = book.snapshot(10);
        assertEquals(1, snap.bids().size());
        assertEquals(0, new BigDecimal("5").compareTo(snap.bids().get(0).qty()));
    }

    @Test
    void zeroQtyUpdateRemovesLevel() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(update(Side.BID, "100", "1"), update(Side.BID, "99", "1")));

        book.applyUpdate(update(Side.BID, "100", "0"));

        assertEquals(1, book.bidDepth());
        assertEquals(0, new BigDecimal("99").compareTo(book.snapshot(10).bids().get(0).price()));
    }

    @Test
    void snapshotOrdersBidsDescendingAndAsksAscending() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(
                update(Side.BID, "100", "1"),
                update(Side.BID, "102", "1"),
                update(Side.BID, "101", "1"),
                update(Side.ASK, "105", "1"),
                update(Side.ASK, "103", "1"),
                update(Side.ASK, "104", "1")
        ));

        OrderBookSnapshot snap = book.snapshot(10);
        assertEquals(List.of("102", "101", "100"),
                snap.bids().stream().map(l -> l.price().toPlainString()).toList());
        assertEquals(List.of("103", "104", "105"),
                snap.asks().stream().map(l -> l.price().toPlainString()).toList());
    }

    @Test
    void snapshotRespectsDepthLimit() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(
                update(Side.BID, "100", "1"),
                update(Side.BID, "99", "1"),
                update(Side.BID, "98", "1")
        ));

        OrderBookSnapshot snap = book.snapshot(2);
        assertEquals(2, snap.bids().size());
    }

    @Test
    void updatesAreDroppedWhileStale() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(update(Side.BID, "100", "1")));
        book.markStale();

        book.applyUpdate(update(Side.BID, "100", "9")); // would-be overwrite

        assertEquals(BookState.STALE, book.state());
        // still the pre-stale value since the update was dropped
        assertEquals(0, new BigDecimal("1").compareTo(book.snapshot(10).bids().get(0).qty()));
    }

    @Test
    void clearForResubscribeEmptiesBookAndMarksStale() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(update(Side.BID, "100", "1"), update(Side.ASK, "101", "1")));

        book.clearForResubscribe();

        assertEquals(BookState.STALE, book.state());
        assertEquals(0, book.bidDepth());
        assertEquals(0, book.askDepth());
    }

    @Test
    void sanityCheckTrueWhenCrossedIsAbsentOrOneSideEmpty() {
        OrderBook book = new OrderBook("BTC-USD");
        assertTrue(book.sanityCheck()); // both sides empty

        book.applySnapshot(List.of(update(Side.BID, "100", "1")));
        assertTrue(book.sanityCheck()); // ask side empty
    }

    @Test
    void sanityCheckFalseWhenBookIsCrossed() {
        OrderBook book = new OrderBook("BTC-USD");
        book.applySnapshot(List.of(update(Side.BID, "100", "1")));
        book.applyUpdate(update(Side.ASK, "99", "1")); // ask below best bid

        assertFalse(book.sanityCheck());
    }
}
