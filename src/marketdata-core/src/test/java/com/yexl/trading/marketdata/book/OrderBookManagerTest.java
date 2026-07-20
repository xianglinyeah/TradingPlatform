package com.yexl.trading.marketdata.book;

import com.yexl.trading.marketdata.model.BookState;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.Side;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

class OrderBookManagerTest {

    @Test
    void getOrCreateCreatesLazilyAndReusesSameInstance() {
        OrderBookManager mgr = new OrderBookManager();

        OrderBook a = mgr.getOrCreate("BTC-USD");
        OrderBook b = mgr.getOrCreate("BTC-USD");

        assertSame(a, b);
        assertEquals("BTC-USD", a.productId());
    }

    @Test
    void getReturnsNullForUnknownProduct() {
        OrderBookManager mgr = new OrderBookManager();
        assertNull(mgr.get("BTC-USD"));
    }

    @Test
    void allReturnsEveryCreatedBook() {
        OrderBookManager mgr = new OrderBookManager();
        mgr.getOrCreate("BTC-USD");
        mgr.getOrCreate("ETH-USD");

        assertEquals(2, mgr.all().size());
    }

    @Test
    void clearAllForResubscribeMarksEveryBookStale() {
        OrderBookManager mgr = new OrderBookManager();
        OrderBook btc = mgr.getOrCreate("BTC-USD");
        OrderBook eth = mgr.getOrCreate("ETH-USD");
        BookUpdate bid = new BookUpdate();
        bid.set(Side.BID, "BTC-USD", new BigDecimal("100"), new BigDecimal("1"), 0L, false);
        btc.applySnapshot(List.of(bid));
        eth.applySnapshot(List.of(bid));

        mgr.clearAllForResubscribe();

        assertEquals(BookState.STALE, btc.state());
        assertEquals(BookState.STALE, eth.state());
    }
}
