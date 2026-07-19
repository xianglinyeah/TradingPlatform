package com.yexl.trading.strategy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.InputStream;
import java.util.Properties;

/**
 * Configuration for the merged Strategy+Execution process. Loaded from
 * {@code strategy.properties} on the classpath; every key can be overridden
 * with a same-named system property ({@code -Dmd.queue.dir=...}), which is
 * how tests and multi-instance launches point at different queues.
 */
public final class StrategyConfig {

    private static final Logger log = LoggerFactory.getLogger(StrategyConfig.class);

    /** Directory of the market data queue to consume (Process A's output). */
    public final String mdQueueDir;
    /** Where to start consuming: "start" = replay whole queue (rebuilds book state from the day's snapshots), "end" = new docs only. */
    public final String tailFrom;

    public final int imbalanceLevels;
    public final double imbalanceThreshold;
    public final long signalCooldownMs;
    /** Docs older than this (publish→consume, wall clock) update the book but never signal — suppresses trading on replayed history during catchup. */
    public final long signalMaxDocAgeMs;

    public final String orderQty;
    public final int riskMaxOrdersPerMinute;
    public final double riskMaxAbsPosition;

    public final String ordersDir;
    public final String auditQueueDir;

    public final int ringBufferSize;
    public final long statsLogIntervalMs;
    /** Latency recording starts this long after the first live (post-catchup) doc — excludes JIT warmup. */
    public final long latencyWarmupMs;
    /** Directory the shutdown latency report is written to. */
    public final String reportsDir;

    /** Simulated order transit: fills execute against the book this much later than the signal. */
    public final long simLatencyMs;
    /** Taker fee applied to every sim fill, in basis points of notional. */
    public final double simFeeBps;
    /** Fraction of displayed level quantity assumed actually available (others race you). */
    public final double simSizeHaircut;

    private StrategyConfig(Properties p) {
        this.mdQueueDir = get(p, "md.queue.dir", "../marketdata-coinbase/queues/md-coinbase");
        this.tailFrom = get(p, "md.tail-from", "start");
        if (!tailFrom.equals("start") && !tailFrom.equals("end")) {
            throw new IllegalArgumentException("md.tail-from must be start|end, got " + tailFrom);
        }

        this.imbalanceLevels = Integer.parseInt(get(p, "imbalance.levels", "5"));
        this.imbalanceThreshold = Double.parseDouble(get(p, "imbalance.threshold", "2.0"));
        if (imbalanceThreshold <= 1.0) {
            throw new IllegalArgumentException("imbalance.threshold must be > 1.0");
        }
        this.signalCooldownMs = Long.parseLong(get(p, "signal.cooldown-ms", "2000"));
        this.signalMaxDocAgeMs = Long.parseLong(get(p, "signal.max-doc-age-ms", "5000"));

        this.orderQty = get(p, "order.qty", "0.001");
        this.riskMaxOrdersPerMinute = Integer.parseInt(get(p, "risk.max-orders-per-minute", "30"));
        this.riskMaxAbsPosition = Double.parseDouble(get(p, "risk.max-abs-position", "0.01"));

        this.ordersDir = get(p, "orders.dir", "orders");
        this.auditQueueDir = get(p, "audit.queue.dir", "queues/signals-audit");

        int rb = Integer.parseInt(get(p, "disruptor.ring-buffer-size", "8192"));
        if (Integer.bitCount(rb) != 1) {
            throw new IllegalArgumentException("disruptor.ring-buffer-size must be a power of two");
        }
        this.ringBufferSize = rb;
        this.statsLogIntervalMs = Long.parseLong(get(p, "metrics.stats-log-interval-ms", "10000"));
        this.latencyWarmupMs = Long.parseLong(get(p, "latency.warmup-ms", "60000"));
        this.reportsDir = get(p, "metrics.reports-dir", "reports");

        this.simLatencyMs = Long.parseLong(get(p, "sim.latency-ms", "15"));
        this.simFeeBps = Double.parseDouble(get(p, "sim.fee-bps", "60"));
        this.simSizeHaircut = Double.parseDouble(get(p, "sim.size-haircut", "0.5"));
        if (simSizeHaircut <= 0 || simSizeHaircut > 1) {
            throw new IllegalArgumentException("sim.size-haircut must be in (0, 1], got " + simSizeHaircut);
        }
    }

    private static String get(Properties p, String key, String dflt) {
        String sys = System.getProperty(key);
        if (sys != null && !sys.isBlank()) {
            return sys.trim();
        }
        return p.getProperty(key, dflt).trim();
    }

    public static StrategyConfig load() {
        Properties props = new Properties();
        try (InputStream is = StrategyConfig.class.getClassLoader().getResourceAsStream("strategy.properties")) {
            if (is != null) {
                props.load(is);
            } else {
                log.warn("strategy.properties not found on classpath, using defaults + system properties");
            }
        } catch (Exception e) {
            throw new RuntimeException("Failed to load strategy.properties", e);
        }
        StrategyConfig cfg = new StrategyConfig(props);
        log.info("StrategyConfig: mdQueue={}, tailFrom={}, imbalance(N={}, T={}), cooldown={}ms, " +
                        "orderQty={}, risk(maxOrders/min={}, maxAbsPos={}), ordersDir={}, auditQueue={}, " +
                        "latencyWarmup={}ms, reportsDir={}",
                cfg.mdQueueDir, cfg.tailFrom, cfg.imbalanceLevels, cfg.imbalanceThreshold,
                cfg.signalCooldownMs, cfg.orderQty, cfg.riskMaxOrdersPerMinute,
                cfg.riskMaxAbsPosition, cfg.ordersDir, cfg.auditQueueDir,
                cfg.latencyWarmupMs, cfg.reportsDir);
        return cfg;
    }
}
