package com.yexl.trading.strategy.handlers;

import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RiskCheckHandlerTest {

    private final List<String> propertiesToClear = new ArrayList<>();

    @AfterEach
    void tearDown() {
        for (String key : propertiesToClear) {
            System.clearProperty(key);
        }
        propertiesToClear.clear();
    }

    private void override(String key, String value) {
        System.setProperty(key, value);
        propertiesToClear.add(key);
    }

    private StrategyConfig streamConfig(int maxOrdersPerMinute, int maxOrdersPerMinutePerProduct,
                                        double maxAbsNotionalUsd) {
        override("clock.mode", "stream");
        override("risk.max-orders-per-minute", String.valueOf(maxOrdersPerMinute));
        override("risk.max-orders-per-minute-per-product", String.valueOf(maxOrdersPerMinutePerProduct));
        override("risk.max-abs-notional-usd", String.valueOf(maxAbsNotionalUsd));
        return StrategyConfig.load();
    }

    private static StrategyEvent signalEvent(String venue, String product, int signal,
                                             String touchPrice, String qty, long recvTs) {
        StrategyEvent event = new StrategyEvent();
        event.delta.venue = venue;
        event.delta.productId = product;
        event.delta.recvTsEpochNanos = recvTs;
        event.signal = signal;
        event.touchPrice = touchPrice;
        event.orderQty = new BigDecimal(qty);
        return event;
    }

    @Test
    void approvesASignalWithinAllLimits() {
        StrategyConfig cfg = streamConfig(30, 15, 1000);
        RiskCheckHandler handler = new RiskCheckHandler(cfg);

        StrategyEvent event = signalEvent("COINBASE", "BTC-USD", StrategyEvent.SIGNAL_BUY, "100", "1", 1_000_000_000L);
        handler.onEvent(event, 0, true);

        assertTrue(event.riskApproved);
        assertEquals(1, handler.approvedCount());
        assertEquals(0, handler.rejectedCount());
    }

    @Test
    void ignoresEventsWithNoSignal() {
        StrategyConfig cfg = streamConfig(30, 15, 1000);
        RiskCheckHandler handler = new RiskCheckHandler(cfg);

        StrategyEvent event = signalEvent("COINBASE", "BTC-USD", StrategyEvent.SIGNAL_NONE, null, "0", 1_000_000_000L);
        handler.onEvent(event, 0, true);

        assertFalse(event.riskApproved);
        assertEquals(0, handler.approvedCount());
        assertEquals(0, handler.rejectedCount());
    }

    @Test
    void rejectsWhenNotionalCapExceeded() {
        StrategyConfig cfg = streamConfig(30, 15, 50); // cap $50
        RiskCheckHandler handler = new RiskCheckHandler(cfg);

        StrategyEvent event = signalEvent("COINBASE", "BTC-USD", StrategyEvent.SIGNAL_BUY, "100", "1", 1_000_000_000L); // $100 notional
        handler.onEvent(event, 0, true);

        assertFalse(event.riskApproved);
        assertTrue(event.riskRejectReason.contains("notional cap"));
        assertEquals(1, handler.rejectedCount());
    }

    @Test
    void rejectsWhenPerProductOrdersPerMinuteCapExceeded() {
        StrategyConfig cfg = streamConfig(30, 1, 100_000); // per-product cap = 1
        RiskCheckHandler handler = new RiskCheckHandler(cfg);

        StrategyEvent e1 = signalEvent("COINBASE", "BTC-USD", StrategyEvent.SIGNAL_BUY, "100", "0.01", 1_000_000_000L);
        handler.onEvent(e1, 0, true);
        StrategyEvent e2 = signalEvent("COINBASE", "BTC-USD", StrategyEvent.SIGNAL_BUY, "100", "0.01", 1_100_000_000L);
        handler.onEvent(e2, 0, true);

        assertTrue(e1.riskApproved);
        assertFalse(e2.riskApproved);
        assertTrue(e2.riskRejectReason.contains("per-product orders-per-minute cap"));
    }

    @Test
    void rejectsWhenGlobalOrdersPerMinuteCapExceeded() {
        StrategyConfig cfg = streamConfig(1, 15, 100_000); // global cap = 1
        RiskCheckHandler handler = new RiskCheckHandler(cfg);

        StrategyEvent e1 = signalEvent("COINBASE", "BTC-USD", StrategyEvent.SIGNAL_BUY, "100", "0.01", 1_000_000_000L);
        handler.onEvent(e1, 0, true);
        StrategyEvent e2 = signalEvent("COINBASE", "ETH-USD", StrategyEvent.SIGNAL_BUY, "100", "0.01", 1_100_000_000L);
        handler.onEvent(e2, 0, true);

        assertTrue(e1.riskApproved);
        assertFalse(e2.riskApproved);
        assertTrue(e2.riskRejectReason.contains("orders-per-minute cap"));
        assertFalse(e2.riskRejectReason.contains("per-product"));
    }
}
