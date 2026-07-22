package com.yexl.trading.strategy;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Exercises StrategyConfig against the real src/main/resources/strategy.properties
 * (present on the test classpath), using system-property overrides — the same
 * mechanism -D launches use — to probe validation and per-product override paths.
 */
class StrategyConfigTest {

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

    @Test
    void loadsDefaultsFromClasspathProperties() {
        StrategyConfig cfg = StrategyConfig.load();

        assertEquals("imbalance", cfg.strategyMode);
        assertEquals(5, cfg.imbalanceLevels);
        assertEquals(2.0, cfg.imbalanceThreshold, 1e-9);
        assertEquals(2000L, cfg.signalCooldownMs);
        assertEquals(100.0, cfg.orderNotionalUsd, 1e-9);
        assertEquals(30, cfg.riskMaxOrdersPerMinute);
        assertEquals("wall", cfg.clockMode);
        assertEquals(8192, cfg.ringBufferSize);
    }

    @Test
    void rejectsImbalanceThresholdNotAboveOne() {
        override("imbalance.threshold", "1.0");
        assertThrows(IllegalArgumentException.class, StrategyConfig::load);
    }

    @Test
    void rejectsUnknownClockMode() {
        override("clock.mode", "bogus");
        assertThrows(IllegalArgumentException.class, StrategyConfig::load);
    }

    @Test
    void rejectsRingBufferSizeThatIsNotAPowerOfTwo() {
        override("disruptor.ring-buffer-size", "100");
        assertThrows(IllegalArgumentException.class, StrategyConfig::load);
    }

    @Test
    void rejectsArbModeWithoutAnyConfiguredSymbol() {
        override("strategy.mode", "arb");
        assertThrows(IllegalArgumentException.class, StrategyConfig::load);
    }

    @Test
    void arbModeParsesTwoLegSymbolDefinitions() {
        override("strategy.mode", "arb");
        override("arb.symbol.BTC", "COINBASE:BTC-USD,OKX:BTC-USDT");

        StrategyConfig cfg = StrategyConfig.load();

        assertTrue(cfg.arbSymbols.containsKey("BTC"));
        assertEquals(List.of("COINBASE", "BTC-USD", "OKX", "BTC-USDT"),
                List.of(cfg.arbSymbols.get("BTC")));
    }

    @Test
    void perProductOrderNotionalOverrideFallsBackToDefaultForOtherProducts() {
        override("order.notional-usd.ETH-USD", "50");

        StrategyConfig cfg = StrategyConfig.load();

        assertEquals(50.0, cfg.orderNotionalUsd("ETH-USD"), 1e-9);
        assertEquals(100.0, cfg.orderNotionalUsd("BTC-USD"), 1e-9);
    }

    @Test
    void perProductRiskCapOverrideFallsBackToDefaultForOtherProducts() {
        override("risk.max-abs-notional-usd.ETH-USD", "2000");

        StrategyConfig cfg = StrategyConfig.load();

        assertEquals(2000.0, cfg.riskMaxAbsNotionalUsd("ETH-USD"), 1e-9);
        assertEquals(1000.0, cfg.riskMaxAbsNotionalUsd("BTC-USD"), 1e-9);
    }

    @Test
    void perVenueSimFeeOverrideFallsBackToDefaultForOtherVenues() {
        StrategyConfig cfg = StrategyConfig.load();

        assertEquals(10.0, cfg.simFeeBps("OKX"), 1e-9); // baked into strategy.properties
        assertEquals(60.0, cfg.simFeeBps("COINBASE"), 1e-9);
    }
}
