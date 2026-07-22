package com.yexl.trading.strategy;

import com.lmax.disruptor.BlockingWaitStrategy;
import com.lmax.disruptor.BusySpinWaitStrategy;
import com.lmax.disruptor.SleepingWaitStrategy;
import com.lmax.disruptor.WaitStrategy;
import com.lmax.disruptor.YieldingWaitStrategy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.InputStream;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

/**
 * Configuration for the merged Strategy+Execution process. Loaded from
 * {@code strategy.properties} on the classpath; every key can be overridden
 * with a same-named system property ({@code -Dmd.queue.dir=...}), which is
 * how tests and multi-instance launches point at different queues.
 */
public final class StrategyConfig {

    private static final Logger log = LoggerFactory.getLogger(StrategyConfig.class);

    /** Market data queues to consume (one per venue; single entry = classic single-venue mode). */
    public final List<String> mdQueueDirs;
    /** Where to start consuming: "start" = replay whole queue (rebuilds book state from the day's snapshots), "end" = new docs only. */
    public final String tailFrom;

    /** "imbalance" (single-venue book imbalance, default) or "arb" (cross-venue basis mean-reversion). */
    public final String strategyMode;
    /** Arb mode: logical symbol -> [venueA, productA, venueB, productB]. */
    public final Map<String, String[]> arbSymbols;
    /** Entry when |spread - EMA(spread)| exceeds this, in bps of mid. */
    public final double arbEntryBps;
    /** Half-life of the irregular-series EMA over the cross-venue spread. */
    public final long arbEmaHalflifeMs;
    /** Spread samples required before the EMA is trusted enough to trade. */
    public final int arbMinSamples;
    /** EMA must also be at least this old (stream time) before trading — sample count alone converges too early. */
    public final long arbEmaWarmupMs;
    /** Both legs' books must have updated within this window for a signal. */
    public final long arbMaxLegAgeMs;

    public final int imbalanceLevels;
    public final double imbalanceThreshold;
    public final long signalCooldownMs;
    /** Docs older than this (publish→consume, wall clock) update the book but never signal — suppresses trading on replayed history during catchup. */
    public final long signalMaxDocAgeMs;

    /** Default order size in USD notional; base qty derived at the signal's touch price. */
    public final double orderNotionalUsd;
    private final Map<String, Double> orderNotionalUsdByProduct;
    /** Process-wide rolling cap across all products. */
    public final int riskMaxOrdersPerMinute;
    /** Per-product rolling cap (second throttle level). */
    public final int riskMaxOrdersPerMinutePerProduct;
    /** Default max absolute net exposure per product, USD notional. */
    public final double riskMaxAbsNotionalUsd;
    private final Map<String, Double> riskMaxAbsNotionalUsdByProduct;

    public final String ordersDir;
    public final String auditQueueDir;

    public final int ringBufferSize;
    public final String waitStrategyName;
    public final WaitStrategy waitStrategy;
    public final long statsLogIntervalMs;
    /** Latency recording starts this long after the first live (post-catchup) doc — excludes JIT warmup. */
    public final long latencyWarmupMs;
    /** Directory the shutdown latency report is written to. */
    public final String reportsDir;

    /**
     * Time source for cooldown / risk windows / doc-age gating.
     * "wall" = system clock (live & paper trading). "stream" = the md docs'
     * own recvTs (backtest replay of an archived queue): time advances only
     * as data advances, doc-age gating is disabled, and draining the queue
     * ends the run. Same binary, one switch — no live/backtest code fork.
     */
    public final String clockMode;

    /** Simulated order transit: fills execute against the book this much later than the signal. */
    public final long simLatencyMs;
    /** Default taker fee applied to every sim fill, in basis points of notional. */
    public final double simFeeBps;
    private final Map<String, Double> simFeeBpsByVenue;
    /** Fraction of displayed level quantity assumed actually available (others race you). */
    public final double simSizeHaircut;

    private StrategyConfig(Properties p) {
        // md.queue.dirs (comma list) preferred; md.queue.dir kept as the
        // single-venue alias so existing launch commands stay valid.
        String dirs = get(p, "md.queue.dirs", "");
        if (dirs.isEmpty()) {
            dirs = get(p, "md.queue.dir", "../marketdata-coinbase/queues/md-coinbase");
        }
        this.mdQueueDirs = Arrays.stream(dirs.split(","))
                .map(String::trim).filter(s -> !s.isEmpty()).toList();
        if (mdQueueDirs.isEmpty()) {
            throw new IllegalArgumentException("md.queue.dirs must list at least one queue");
        }
        this.tailFrom = get(p, "md.tail-from", "start");

        this.strategyMode = get(p, "strategy.mode", "imbalance");
        if (!strategyMode.equals("imbalance") && !strategyMode.equals("arb")) {
            throw new IllegalArgumentException("strategy.mode must be imbalance|arb, got " + strategyMode);
        }
        this.arbSymbols = parseArbSymbols(p);
        this.arbEntryBps = Double.parseDouble(get(p, "arb.entry-bps", "3.0"));
        this.arbEmaHalflifeMs = Long.parseLong(get(p, "arb.ema-halflife-ms", "60000"));
        this.arbMinSamples = Integer.parseInt(get(p, "arb.min-samples", "200"));
        this.arbEmaWarmupMs = Long.parseLong(get(p, "arb.ema-warmup-ms",
                String.valueOf(2 * this.arbEmaHalflifeMs)));
        this.arbMaxLegAgeMs = Long.parseLong(get(p, "arb.max-leg-age-ms", "500"));
        if (arbEntryBps <= 0 || arbEmaHalflifeMs <= 0 || arbMinSamples < 1
                || arbEmaWarmupMs <= 0 || arbMaxLegAgeMs <= 0) {
            throw new IllegalArgumentException("arb.* parameters must all be positive");
        }
        if (strategyMode.equals("arb") && arbSymbols.isEmpty()) {
            throw new IllegalArgumentException(
                    "strategy.mode=arb requires at least one arb.symbol.<SYM>=VENUE:PROD,VENUE:PROD");
        }
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

        this.orderNotionalUsd = Double.parseDouble(get(p, "order.notional-usd", "100"));
        this.orderNotionalUsdByProduct = perProductOverrides(p, "order.notional-usd.");
        this.riskMaxOrdersPerMinute = Integer.parseInt(get(p, "risk.max-orders-per-minute", "30"));
        this.riskMaxOrdersPerMinutePerProduct =
                Integer.parseInt(get(p, "risk.max-orders-per-minute-per-product", "15"));
        this.riskMaxAbsNotionalUsd = Double.parseDouble(get(p, "risk.max-abs-notional-usd", "1000"));
        this.riskMaxAbsNotionalUsdByProduct = perProductOverrides(p, "risk.max-abs-notional-usd.");
        if (orderNotionalUsd <= 0 || riskMaxAbsNotionalUsd <= 0) {
            throw new IllegalArgumentException("order.notional-usd and risk.max-abs-notional-usd must be > 0");
        }

        this.ordersDir = get(p, "orders.dir", "orders");
        this.auditQueueDir = get(p, "audit.queue.dir", "queues/signals-audit");

        int rb = Integer.parseInt(get(p, "disruptor.ring-buffer-size", "8192"));
        if (Integer.bitCount(rb) != 1) {
            throw new IllegalArgumentException("disruptor.ring-buffer-size must be a power of two");
        }
        this.ringBufferSize = rb;
        this.waitStrategyName = get(p, "disruptor.wait-strategy", "yielding").trim().toLowerCase();
        this.waitStrategy = switch (waitStrategyName) {
            case "yielding" -> new YieldingWaitStrategy();
            case "blocking" -> new BlockingWaitStrategy();
            case "sleeping" -> new SleepingWaitStrategy();
            case "busy" -> new BusySpinWaitStrategy();
            default -> throw new IllegalArgumentException(
                    "Unknown wait-strategy: " + waitStrategyName +
                    " (expected one of: yielding, blocking, sleeping, busy)");
        };
        this.statsLogIntervalMs = Long.parseLong(get(p, "metrics.stats-log-interval-ms", "10000"));
        this.latencyWarmupMs = Long.parseLong(get(p, "latency.warmup-ms", "60000"));
        this.reportsDir = get(p, "metrics.reports-dir", "reports");

        this.clockMode = get(p, "clock.mode", "wall");
        if (!clockMode.equals("wall") && !clockMode.equals("stream")) {
            throw new IllegalArgumentException("clock.mode must be wall|stream, got " + clockMode);
        }

        this.simLatencyMs = Long.parseLong(get(p, "sim.latency-ms", "15"));
        this.simFeeBps = Double.parseDouble(get(p, "sim.fee-bps", "60"));
        this.simFeeBpsByVenue = perProductOverrides(p, "sim.fee-bps.");
        this.simSizeHaircut = Double.parseDouble(get(p, "sim.size-haircut", "0.5"));
        if (simSizeHaircut <= 0 || simSizeHaircut > 1) {
            throw new IllegalArgumentException("sim.size-haircut must be in (0, 1], got " + simSizeHaircut);
        }
    }

    /** Effective per-product order notional (override or default). */
    public double orderNotionalUsd(String product) {
        return orderNotionalUsdByProduct.getOrDefault(product, orderNotionalUsd);
    }

    /** Effective per-venue sim taker fee (override or default). */
    public double simFeeBps(String venue) {
        return simFeeBpsByVenue.getOrDefault(venue, simFeeBps);
    }

    /**
     * Parses {@code arb.symbol.<SYM>=VENUE:PROD,VENUE:PROD} entries (property
     * file + system properties, system wins) into SYM -> [venA, prodA, venB, prodB].
     */
    private static Map<String, String[]> parseArbSymbols(Properties p) {
        Map<String, String[]> m = new HashMap<>();
        String prefix = "arb.symbol.";
        Set<String> keys = new HashSet<>(p.stringPropertyNames());
        keys.addAll(System.getProperties().stringPropertyNames());
        for (String key : keys) {
            if (!key.startsWith(prefix)) {
                continue;
            }
            String v = System.getProperty(key);
            if (v == null || v.isBlank()) {
                v = p.getProperty(key);
            }
            if (v == null || v.isBlank()) {
                continue;
            }
            String[] legs = v.trim().split(",");
            if (legs.length != 2) {
                throw new IllegalArgumentException(key + " must have exactly two legs, got: " + v);
            }
            String[] a = legs[0].trim().split(":");
            String[] b = legs[1].trim().split(":");
            if (a.length != 2 || b.length != 2) {
                throw new IllegalArgumentException(key + " legs must be VENUE:PRODUCT, got: " + v);
            }
            m.put(key.substring(prefix.length()), new String[]{a[0], a[1], b[0], b[1]});
        }
        return Map.copyOf(m);
    }

    /** Effective per-product max absolute exposure (override or default). */
    public double riskMaxAbsNotionalUsd(String product) {
        return riskMaxAbsNotionalUsdByProduct.getOrDefault(product, riskMaxAbsNotionalUsd);
    }

    /**
     * Collects {@code <prefix><PRODUCT-ID>=<double>} keys from the property
     * file and system properties (system wins, same as {@link #get}).
     */
    private static Map<String, Double> perProductOverrides(Properties p, String prefix) {
        Map<String, Double> m = new HashMap<>();
        Set<String> keys = new HashSet<>(p.stringPropertyNames());
        keys.addAll(System.getProperties().stringPropertyNames());
        for (String key : keys) {
            if (!key.startsWith(prefix)) {
                continue;
            }
            String v = System.getProperty(key);
            if (v == null || v.isBlank()) {
                v = p.getProperty(key);
            }
            if (v != null && !v.isBlank()) {
                m.put(key.substring(prefix.length()), Double.parseDouble(v.trim()));
            }
        }
        return Map.copyOf(m);
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
        log.info("StrategyConfig: mode={}, arbSymbols={}, clockMode={}, mdQueues={}, tailFrom={}, imbalance(N={}, T={}), cooldown={}ms, " +
                        "orderNotionalUsd={} (overrides={}), risk(maxOrders/min={}, perProduct/min={}, " +
                        "maxAbsNotionalUsd={} overrides={}), ordersDir={}, auditQueue={}, " +
                        "latencyWarmup={}ms, reportsDir={}",
                cfg.strategyMode, cfg.arbSymbols.keySet(),
                cfg.clockMode, cfg.mdQueueDirs, cfg.tailFrom, cfg.imbalanceLevels, cfg.imbalanceThreshold,
                cfg.signalCooldownMs, cfg.orderNotionalUsd, cfg.orderNotionalUsdByProduct,
                cfg.riskMaxOrdersPerMinute, cfg.riskMaxOrdersPerMinutePerProduct,
                cfg.riskMaxAbsNotionalUsd, cfg.riskMaxAbsNotionalUsdByProduct,
                cfg.ordersDir, cfg.auditQueueDir,
                cfg.latencyWarmupMs, cfg.reportsDir);
        return cfg;
    }
}
