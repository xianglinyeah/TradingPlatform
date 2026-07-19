package com.yexl.trading.coinbase.config;

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
 * Immutable application configuration loaded from {@code application.properties}
 * on the classpath, with environment-variable overrides for secrets.
 *
 * <p>Resolution order for credentials:
 * <ol>
 *   <li>Environment variable ({@code COINBASE_API_KEY} / {@code COINBASE_SIGNING_KEY_PATH}).</li>
 *   <li>Property file value (typically a {@code ${ENV_VAR}} placeholder, which
 *       Java's {@link Properties} does NOT expand — so the env-var path is the
 *       primary mechanism for production).</li>
 * </ol>
 */
public final class AppConfig {

    private static final Logger log = LoggerFactory.getLogger(AppConfig.class);

    public final String wsUrl;
    public final List<String> productIds;

    public final String apiKey;
    public final String signingKeyPath;
    public final int jwtTtlSeconds;
    public final int jwtRefreshBeforeExpSeconds;

    public final long heartbeatExpectedIntervalMs;
    public final int heartbeatMissedThreshold;

    public final long reconnectInitialBackoffMs;
    public final long reconnectMaxBackoffMs;

    public final int ringBufferSize;
    public final WaitStrategy waitStrategy;
    public final String waitStrategyName;

    public final int maxUpdatesPerEvent;
    public final long snapshotLogIntervalMs;
    public final int snapshotLogDepth;

    public final int wsMaxFrameBytes;

    public final boolean proxyEnabled;
    public final String proxyType;
    public final String proxyHost;
    public final int proxyPort;

    public final long latencyLogIntervalMs;

    public final boolean recordingEnabled;
    public final String recordingDir;

    /** Venue tag stamped into every published delta (multi-venue readiness). */
    public final String venue;
    public final boolean chroniclePublishEnabled;
    public final String chronicleQueueDir;

    private AppConfig(Properties p) {
        this.wsUrl = require(p, "coinbase.ws.url");
        this.productIds = Arrays.stream(require(p, "coinbase.product.ids").split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
        if (this.productIds.isEmpty()) {
            throw new IllegalArgumentException("coinbase.product.ids must list at least one product");
        }

        this.apiKey = resolveEnvOrProp(p, "COINBASE_API_KEY", "coinbase.auth.api-key");
        this.signingKeyPath = resolveEnvOrProp(p, "COINBASE_SIGNING_KEY_PATH", "coinbase.auth.signing-key-path");
        this.jwtTtlSeconds = parseInt(p, "coinbase.auth.jwt-ttl-seconds", 120);
        this.jwtRefreshBeforeExpSeconds = parseInt(p, "coinbase.auth.jwt-refresh-before-exp-seconds", 60);

        this.heartbeatExpectedIntervalMs = parseLong(p, "coinbase.heartbeat.expected-interval-ms", 1000L);
        this.heartbeatMissedThreshold = parseInt(p, "coinbase.heartbeat.missed-threshold", 3);

        this.reconnectInitialBackoffMs = parseLong(p, "coinbase.reconnect.initial-backoff-ms", 1000L);
        this.reconnectMaxBackoffMs = parseLong(p, "coinbase.reconnect.max-backoff-ms", 30_000L);
        if (this.reconnectInitialBackoffMs <= 0 || this.reconnectMaxBackoffMs < this.reconnectInitialBackoffMs) {
            throw new IllegalArgumentException(
                    "coinbase.reconnect.initial-backoff-ms must be > 0 and <= max-backoff-ms");
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

        this.maxUpdatesPerEvent = parseInt(p, "orderbook.max-updates-per-event", 8192);
        this.snapshotLogIntervalMs = parseLong(p, "orderbook.snapshot-log-interval-ms", 1000L);
        this.snapshotLogDepth = parseInt(p, "orderbook.snapshot-log-depth", 10);

        // 8MB default: a full BTC-USD level2 snapshot (thousands of price
        // levels) can exceed the WebSocket default of 64KB and the previous
        // hardcoded 1MB cap.
        this.wsMaxFrameBytes = parseInt(p, "coinbase.ws.max-frame-bytes", 8 * 1024 * 1024);

        this.proxyEnabled = Boolean.parseBoolean(p.getProperty("coinbase.proxy.enabled", "false").trim());
        this.proxyType = p.getProperty("coinbase.proxy.type", "socks5").trim().toLowerCase();
        this.proxyHost = p.getProperty("coinbase.proxy.host", "127.0.0.1").trim();
        this.proxyPort = parseInt(p, "coinbase.proxy.port", 10808);
        if (proxyEnabled && !proxyType.equals("socks5") && !proxyType.equals("http")) {
            throw new IllegalArgumentException(
                    "coinbase.proxy.type must be socks5 or http, got " + proxyType);
        }

        this.latencyLogIntervalMs = parseLong(p, "metrics.latency-log-interval-ms", 10_000L);

        this.recordingEnabled = Boolean.parseBoolean(p.getProperty("recording.enabled", "false").trim());
        this.recordingDir = p.getProperty("recording.dir", "recordings").trim();

        this.venue = p.getProperty("venue", "COINBASE").trim();
        this.chroniclePublishEnabled = Boolean.parseBoolean(
                p.getProperty("chronicle.publish.enabled", "true").trim());
        this.chronicleQueueDir = p.getProperty("chronicle.queue.dir", "queues/md-coinbase").trim();
    }

    public static AppConfig load() {
        Properties props = new Properties();
        try (InputStream is = AppConfig.class.getClassLoader().getResourceAsStream("application.properties")) {
            if (is != null) {
                props.load(is);
            } else {
                log.warn("application.properties not found on classpath, using defaults + env vars");
            }
        } catch (Exception e) {
            throw new RuntimeException("Failed to load application.properties", e);
        }
        // System-property overrides for any key present in the file
        // (e.g. -Dcoinbase.heartbeat.missed-threshold=3 for fault-injection runs).
        for (String key : props.stringPropertyNames()) {
            String sys = System.getProperty(key);
            if (sys != null && !sys.isBlank()) {
                props.setProperty(key, sys.trim());
                log.info("Config override from system property: {}={}", key, sys.trim());
            }
        }
        AppConfig cfg = new AppConfig(props);
        log.info("AppConfig: products={}, ringBufferSize={}, waitStrategy={}, wsUrl={}, proxy={}",
                cfg.productIds, cfg.ringBufferSize, cfg.waitStrategyName, cfg.wsUrl,
                cfg.proxyEnabled ? (cfg.proxyType + "://" + cfg.proxyHost + ":" + cfg.proxyPort) : "disabled");
        return cfg;
    }

    private static String resolveEnvOrProp(Properties p, String envVar, String propKey) {
        String env = System.getenv(envVar);
        if (env != null && !env.isBlank()) {
            return env;
        }
        String val = p.getProperty(propKey);
        // Filter out unexpanded ${VAR} placeholders.
        if (val != null && val.startsWith("${") && val.endsWith("}")) {
            return null;
        }
        return val;
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
