package com.yexl.trading.strategy.handlers;

import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.marketdata.wire.MdDelta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class SignalHandlerTest {

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

    private StrategyConfig streamConfig(int levels, double threshold, long cooldownMs) {
        override("clock.mode", "stream");
        override("imbalance.levels", String.valueOf(levels));
        override("imbalance.threshold", String.valueOf(threshold));
        override("signal.cooldown-ms", String.valueOf(cooldownMs));
        override("order.notional-usd", "100");
        return StrategyConfig.load();
    }

    /** One venue-neutral snapshot doc with the given (side, price, qty) triples. */
    private static StrategyEvent snapshotEvent(String product, long recvTs, Object... levels) {
        StrategyEvent event = new StrategyEvent();
        MdDelta d = event.delta;
        d.venue = "COINBASE";
        d.productId = product;
        d.snapshot = true;
        d.recvTsEpochNanos = recvTs;
        d.pubTsEpochNanos = recvTs;
        int n = levels.length / 3;
        d.prepareLevels(n);
        for (int i = 0; i < n; i++) {
            d.setLevel(i, (byte) levels[i * 3], (String) levels[i * 3 + 1], (String) levels[i * 3 + 2]);
        }
        return event;
    }

    @Test
    void noSignalUntilBookHasEnoughLevelsOnBothSides() {
        StrategyConfig cfg = streamConfig(2, 2.0, 1000);
        SignalHandler handler = new SignalHandler(cfg);

        StrategyEvent event = snapshotEvent("BTC-USD", 1_000_000_000L,
                MdDelta.SIDE_BID, "100", "5",
                MdDelta.SIDE_ASK, "101", "1"); // only 1 level per side, need 2

        handler.onEvent(event, 0, true);

        assertEquals(StrategyEvent.SIGNAL_NONE, event.signal);
        assertEquals(0, handler.signalsGeneratedCount());
    }

    @Test
    void bidHeavyImbalanceEmitsBuySignalAtBestAsk() {
        StrategyConfig cfg = streamConfig(2, 2.0, 1000);
        SignalHandler handler = new SignalHandler(cfg);

        StrategyEvent event = snapshotEvent("BTC-USD", 1_000_000_000L,
                MdDelta.SIDE_BID, "100", "5",
                MdDelta.SIDE_BID, "99", "5",
                MdDelta.SIDE_ASK, "101", "1",
                MdDelta.SIDE_ASK, "102", "1");

        handler.onEvent(event, 0, true);

        assertEquals(StrategyEvent.SIGNAL_BUY, event.signal);
        assertEquals("101", event.touchPrice);
        BigDecimal expectedQty = BigDecimal.valueOf(100).divide(new BigDecimal("101"), 8, RoundingMode.DOWN);
        assertEquals(0, expectedQty.compareTo(event.orderQty));
        assertEquals(1, handler.signalsGeneratedCount());
    }

    @Test
    void askHeavyImbalanceEmitsSellSignalAtBestBid() {
        StrategyConfig cfg = streamConfig(2, 2.0, 1000);
        SignalHandler handler = new SignalHandler(cfg);

        StrategyEvent event = snapshotEvent("BTC-USD", 1_000_000_000L,
                MdDelta.SIDE_BID, "100", "1",
                MdDelta.SIDE_BID, "99", "1",
                MdDelta.SIDE_ASK, "101", "5",
                MdDelta.SIDE_ASK, "102", "5");

        handler.onEvent(event, 0, true);

        assertEquals(StrategyEvent.SIGNAL_SELL, event.signal);
        assertEquals("100", event.touchPrice);
    }

    @Test
    void balancedBookBelowThresholdEmitsNoSignal() {
        StrategyConfig cfg = streamConfig(2, 2.0, 1000);
        SignalHandler handler = new SignalHandler(cfg);

        StrategyEvent event = snapshotEvent("BTC-USD", 1_000_000_000L,
                MdDelta.SIDE_BID, "100", "3",
                MdDelta.SIDE_BID, "99", "3",
                MdDelta.SIDE_ASK, "101", "3",
                MdDelta.SIDE_ASK, "102", "3");

        handler.onEvent(event, 0, true);

        assertEquals(StrategyEvent.SIGNAL_NONE, event.signal);
        assertNull(event.touchPrice);
    }

    @Test
    void cooldownSuppressesRepeatSignalsUntilWindowElapses() {
        StrategyConfig cfg = streamConfig(2, 2.0, 1000); // 1000ms cooldown
        SignalHandler handler = new SignalHandler(cfg);
        Object[] imbalancedLevels = {
                MdDelta.SIDE_BID, "100", "5",
                MdDelta.SIDE_BID, "99", "5",
                MdDelta.SIDE_ASK, "101", "1",
                MdDelta.SIDE_ASK, "102", "1"
        };

        StrategyEvent e1 = snapshotEvent("BTC-USD", 1_000_000_000L, imbalancedLevels);
        handler.onEvent(e1, 0, true);
        assertEquals(StrategyEvent.SIGNAL_BUY, e1.signal);

        StrategyEvent e2 = snapshotEvent("BTC-USD", 1_500_000_000L, imbalancedLevels); // +0.5s, within 1s cooldown
        handler.onEvent(e2, 0, true);
        assertEquals(StrategyEvent.SIGNAL_NONE, e2.signal);

        StrategyEvent e3 = snapshotEvent("BTC-USD", 3_000_000_000L, imbalancedLevels); // +2s, cooldown elapsed
        handler.onEvent(e3, 0, true);
        assertEquals(StrategyEvent.SIGNAL_BUY, e3.signal);

        assertEquals(2, handler.signalsGeneratedCount());
    }
}
