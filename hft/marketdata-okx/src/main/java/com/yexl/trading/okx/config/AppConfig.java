package com.yexl.trading.okx.config;

import com.lmax.disruptor.BlockingWaitStrategy;
import com.lmax.disruptor.BusySpinWaitStrategy;
import com.lmax.disruptor.SleepingWaitStrategy;
import com.lmax.disruptor.WaitStrategy;
import com.lmax.disruptor.YieldingWaitStrategy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.InputStream;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;

/**
 * Immutable configuration for the OKX market data process, loaded from
 * {@code application.properties} on the classpath with same-named system
 * property overrides. No credentials: the OKX public books channel is
 * unauthenticated (API keys enter only with the future execution adapter).
 */
public final class AppConfig {

    private static final Logger log = LoggerFactory.getLogger(AppConfig.class);

    public final String wsUrl;
    public final List<String> productIds;

    /** Client-side "ping" send interval (OKX liveness is client-driven). */
    public final long pingIntervalMs;
    public final long heartbeatExpectedIntervalMs;
    public final int heartbeatMissedThreshold;

    public final long reconnectInitialBackoffMs;
    public final long reconnectMaxBackoffMs;

    public final int ringBufferSize;
    public final WaitStrategy waitStrategy;
    public final String waitStrategyName;

    public final long snapshotLogIntervalMs;
    public final int snapshotLogDepth;

    /** Verify OKX's per-frame CRC32 book checksum after each apply. */
    public final boolean checksumEnabled;

    public final int wsMaxFrameBytes;

    public final boolean proxyEnabled;
    public final String proxyType;
    public final String proxyHost;
    public final int proxyPort;

    public final long latencyLogIntervalMs;

    /** Venue tag stamped into every published delta. */
    public final String venue;
    public final boolean chroniclePublishEnabled;
    public final String chronicleQueueDir;

    private AppConfig(Properties p) {
        this.wsUrl = require(p, "okx.ws.url");
        this.productIds = Arrays.stream(require(p, "okx.product.ids").split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
        if (this.productIds.isEmpty()) {
            throw new IllegalArgumentException("okx.product.ids must list at least one instrument");
        }

        this.pingIntervalMs = parseLong(p, "okx.ping-interval-ms", 15_000L);
        this.heartbeatExpectedIntervalMs = parseLong(p, "okx.heartbeat.expected-interval-ms", 15_000L);
        this.heartbeatMissedThreshold = parseInt(p, "okx.heartbeat.missed-threshold", 3);

        this.reconnectInitialBackoffMs = parseLong(p, "okx.reconnect.initial-backoff-ms", 1000L);
        this.reconnectMaxBackoffMs = parseLong(p, "okx.reconnect.max-backoff-ms", 30_000L);
        if (this.reconnectInitialBackoffMs <= 0 || this.reconnectMaxBackoffMs < this.reconnectInitialBackoffMs) {
            throw new IllegalArgumentException(
                    "okx.reconnect.initial-backoff-ms must be > 0 and <= max-backoff-ms");
        }

        int rb = parseInt(p, "disruptor.ring-buffer-size", 8192);
        if (Integer.bitCount(rb) != 1) {
            throw new IllegalArgumentException(
                    "disruptor.ring-buffer-size must be a power of two, got " + rb);
        }
        this.ringBufferSize = rb;
        this.waitStrategyName = p.getProperty("disruptor.wait-strategy", "yielding").trim().toLowerCase();
        this.waitStrategy = switch (waitStrategyName) {
            case "yielding" -> new YieldingWaitStrategy();
            case "blocking" -> new BlockingWaitStrategy();
            case "sleeping" -> new SleepingWaitStrategy();
            case "busy" -> new BusySpinWaitStrategy();
            default -> throw new IllegalArgumentException(
                    "Unknown wait-strategy: " + waitStrategyName +
                    " (expected one of: yielding, blocking, sleeping, busy)");
        };

        this.snapshotLogIntervalMs = parseLong(p, "orderbook.snapshot-log-interval-ms", 1000L);
        this.snapshotLogDepth = parseInt(p, "orderbook.snapshot-log-depth", 10);

        this.checksumEnabled = Boolean.parseBoolean(
                p.getProperty("okx.checksum.enabled", "true").trim());

        this.wsMaxFrameBytes = parseInt(p, "okx.ws.max-frame-bytes", 2 * 1024 * 1024);

        this.proxyEnabled = Boolean.parseBoolean(p.getProperty("okx.proxy.enabled", "false").trim());
        this.proxyType = p.getProperty("okx.proxy.type", "socks5").trim().toLowerCase();
        this.proxyHost = p.getProperty("okx.proxy.host", "127.0.0.1").trim();
        this.proxyPort = parseInt(p, "okx.proxy.port", 10808);
        if (proxyEnabled && !proxyType.equals("socks5") && !proxyType.equals("http")) {
            throw new IllegalArgumentException(
                    "okx.proxy.type must be socks5 or http, got " + proxyType);
        }

        this.latencyLogIntervalMs = parseLong(p, "metrics.latency-log-interval-ms", 10_000L);

        this.venue = p.getProperty("venue", "OKX").trim();
        this.chroniclePublishEnabled = Boolean.parseBoolean(
                p.getProperty("chronicle.publish.enabled", "true").trim());
        this.chronicleQueueDir = p.getProperty("chronicle.queue.dir", "queues/md-okx").trim();
    }

    public static AppConfig load() {
        Properties props = new Properties();
        try (InputStream is = AppConfig.class.getClassLoader().getResourceAsStream("application.properties")) {
            if (is != null) {
                props.load(is);
            } else {
                log.warn("application.properties not found on classpath, using defaults");
            }
        } catch (Exception e) {
            throw new RuntimeException("Failed to load application.properties", e);
        }
        for (String key : props.stringPropertyNames()) {
            String sys = System.getProperty(key);
            if (sys != null && !sys.isBlank()) {
                props.setProperty(key, sys.trim());
                log.info("Config override from system property: {}={}", key, sys.trim());
            }
        }
        AppConfig cfg = new AppConfig(props);
        log.info("AppConfig: products={}, ringBufferSize={}, waitStrategy={}, wsUrl={}, proxy={}, ping={}ms",
                cfg.productIds, cfg.ringBufferSize, cfg.waitStrategyName, cfg.wsUrl,
                cfg.proxyEnabled ? (cfg.proxyType + "://" + cfg.proxyHost + ":" + cfg.proxyPort) : "disabled",
                cfg.pingIntervalMs);
        return cfg;
    }

    private static String require(Properties p, String key) {
        String v = p.getProperty(key);
        if (v == null || v.isBlank()) {
            throw new IllegalArgumentException("Missing required config: " + key);
        }
        return v.trim();
    }

    private static int parseInt(Properties p, String key, int dflt) {
        String v = p.getProperty(key);
        if (v == null || v.isBlank()) {
            return dflt;
        }
        try {
            return Integer.parseInt(v.trim());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("Invalid int for " + key + ": " + v);
        }
    }

    private static long parseLong(Properties p, String key, long dflt) {
        String v = p.getProperty(key);
        if (v == null || v.isBlank()) {
            return dflt;
        }
        try {
            return Long.parseLong(v.trim());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("Invalid long for " + key + ": " + v);
        }
    }
}
