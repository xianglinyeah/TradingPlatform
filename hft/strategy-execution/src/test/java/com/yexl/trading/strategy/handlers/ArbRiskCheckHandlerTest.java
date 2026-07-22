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

class ArbRiskCheckHandlerTest {

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
        override("strategy.mode", "arb");
        override("arb.symbol.BTC", "COINBASE:BTC-USD,OKX:BTC-USDT");
        override("risk.max-orders-per-minute", String.valueOf(maxOrdersPerMinute));
        override("risk.max-orders-per-minute-per-product", String.valueOf(maxOrdersPerMinutePerProduct));
        override("risk.max-abs-notional-usd", String.valueOf(maxAbsNotionalUsd));
        return StrategyConfig.load();
    }

    private static StrategyEvent arbEvent(String buyVenue, String buyProduct, String buyQty, String buyTouch,
                                          String sellVenue, String sellProduct, String sellQty, String sellTouch,
                                          long recvTs) {
        StrategyEvent event = new StrategyEvent();
        event.delta.recvTsEpochNanos = recvTs;
        event.arbSignal = true;
        event.arbSymbol = "BTC";
        event.arbBuyLeg.venue = buyVenue;
        event.arbBuyLeg.productId = buyProduct;
        event.arbBuyLeg.qty = new BigDecimal(buyQty);
        event.arbBuyLeg.touchPrice = buyTouch;
        event.arbSellLeg.venue = sellVenue;
        event.arbSellLeg.productId = sellProduct;
        event.arbSellLeg.qty = new BigDecimal(sellQty);
        event.arbSellLeg.touchPrice = sellTouch;
        return event;
    }

    @Test
    void approvesBothLegsAtomicallyWithinLimits() {
        StrategyConfig cfg = streamConfig(30, 15, 1000);
        ArbRiskCheckHandler handler = new ArbRiskCheckHandler(cfg);

        StrategyEvent event = arbEvent("COINBASE", "BTC-USD", "0.1", "100",
                "OKX", "BTC-USDT", "0.1", "100.1", 1_000_000_000L);
        handler.onEvent(event, 0, true);

        assertTrue(event.riskApproved);
        assertEquals(1, handler.approvedCount());
    }

    @Test
    void ignoresNonArbEvents() {
        StrategyConfig cfg = streamConfig(30, 15, 1000);
        ArbRiskCheckHandler handler = new ArbRiskCheckHandler(cfg);

        StrategyEvent event = new StrategyEvent();
        event.arbSignal = false;
        handler.onEvent(event, 0, true);

        assertFalse(event.riskApproved);
        assertEquals(0, handler.approvedCount());
        assertEquals(0, handler.rejectedCount());
    }

    @Test
    void rejectsWhenNotionalCapExceededOnEitherLeg() {
        StrategyConfig cfg = streamConfig(30, 15, 5); // cap $5

        ArbRiskCheckHandler handler = new ArbRiskCheckHandler(cfg);

        StrategyEvent event = arbEvent("COINBASE", "BTC-USD", "1", "100", // $100 notional
                "OKX", "BTC-USDT", "1", "100", 1_000_000_000L);
        handler.onEvent(event, 0, true);

        assertFalse(event.riskApproved);
        assertTrue(event.riskRejectReason.contains("notional cap"));
        assertEquals(1, handler.rejectedCount());
    }

    @Test
    void rejectsSecondArbWhenGlobalCapWouldBeExceeded() {
        // Each arb consumes 2 of the global budget; cap=2 allows exactly one pair.
        StrategyConfig cfg = streamConfig(2, 15, 100_000);
        ArbRiskCheckHandler handler = new ArbRiskCheckHandler(cfg);

        StrategyEvent e1 = arbEvent("COINBASE", "BTC-USD", "0.01", "100",
                "OKX", "BTC-USDT", "0.01", "100", 1_000_000_000L);
        handler.onEvent(e1, 0, true);
        StrategyEvent e2 = arbEvent("COINBASE", "BTC-USD", "0.01", "100",
                "OKX", "BTC-USDT", "0.01", "100", 1_100_000_000L);
        handler.onEvent(e2, 0, true);

        assertTrue(e1.riskApproved);
        assertFalse(e2.riskApproved);
        assertTrue(e2.riskRejectReason.contains("orders-per-minute cap"));
    }

    @Test
    void rejectsWhenPerLegOrdersPerMinuteCapExceeded() {
        StrategyConfig cfg = streamConfig(30, 1, 100_000); // per-leg cap = 1
        ArbRiskCheckHandler handler = new ArbRiskCheckHandler(cfg);

        StrategyEvent e1 = arbEvent("COINBASE", "BTC-USD", "0.01", "100",
                "OKX", "BTC-USDT", "0.01", "100", 1_000_000_000L);
        handler.onEvent(e1, 0, true);
        StrategyEvent e2 = arbEvent("COINBASE", "BTC-USD", "0.01", "100",
                "OKX", "BTC-USDT", "0.01", "100", 1_100_000_000L);
        handler.onEvent(e2, 0, true);

        assertTrue(e1.riskApproved);
        assertFalse(e2.riskApproved);
        assertTrue(e2.riskRejectReason.contains("per-product orders-per-minute cap"));
    }
}
