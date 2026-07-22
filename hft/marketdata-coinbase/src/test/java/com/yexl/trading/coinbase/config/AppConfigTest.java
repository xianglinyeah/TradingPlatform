package com.yexl.trading.coinbase.config;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Exercises AppConfig against the real src/main/resources/application.properties
 * (present on the test classpath), using system-property overrides — the same
 * mechanism production fault-injection runs use — to probe validation paths.
 */
class AppConfigTest {

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
        AppConfig cfg = AppConfig.load();

        assertEquals("wss://advanced-trade-ws.coinbase.com", cfg.wsUrl);
        assertEquals(List.of("BTC-USD", "ETH-USD"), cfg.productIds);
        assertEquals(8192, cfg.ringBufferSize);
        assertEquals("yielding", cfg.waitStrategyName);
        assertEquals("COINBASE", cfg.venue);
        assertTrue(cfg.chroniclePublishEnabled);
        assertFalse(cfg.recordingEnabled);
    }

    @Test
    void rejectsRingBufferSizeThatIsNotAPowerOfTwo() {
        override("disruptor.ring-buffer-size", "100");
        assertThrows(IllegalArgumentException.class, AppConfig::load);
    }

    @Test
    void rejectsMaxBackoffBelowInitialBackoff() {
        override("coinbase.reconnect.initial-backoff-ms", "5000");
        override("coinbase.reconnect.max-backoff-ms", "1000");
        assertThrows(IllegalArgumentException.class, AppConfig::load);
    }

    @Test
    void rejectsUnknownProxyType() {
        override("coinbase.proxy.enabled", "true");
        override("coinbase.proxy.type", "ftp");
        assertThrows(IllegalArgumentException.class, AppConfig::load);
    }

    @Test
    void rejectsUnknownWaitStrategy() {
        override("disruptor.wait-strategy", "spinny");
        assertThrows(IllegalArgumentException.class, AppConfig::load);
    }
}
