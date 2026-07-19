package com.yexl.trading.strategy.metrics;

import com.yexl.trading.strategy.StrategyEvent;
import org.HdrHistogram.Histogram;
import org.HdrHistogram.Recorder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * Latency histograms for the Strategy+Execution pipeline. Same two-clock
 * discipline as the publisher's LatencyTracker:
 * <ul>
 *   <li>{@code pub->consume} — publisher's epoch stamp vs this process's
 *       epoch stamp. Same-host, so skew is negligible, but still epoch-based
 *       because nanoTime origins differ across JVMs.</li>
 *   <li>{@code consume->placed} — monotonic nanoTime within this process.</li>
 *   <li>{@code exch->placed} — the headline end-to-end number, epoch-based,
 *       includes network transit and NTP-bounded skew (trend indicator).</li>
 * </ul>
 *
 * <p><b>Signed recording.</b> Epoch-based segments can go negative — the
 * exchange's clock running ahead of the local clock makes exch→consume
 * negative for every sample, and clamping those to 0 produced a meaningless
 * p50=0. Each segment therefore keeps two histograms — positive values and
 * negative magnitudes — and merges them for percentiles. (An offset-shifted
 * single histogram would lose precision: HdrHistogram bucket width is
 * relative to the recorded value's magnitude, so shifting a 30µs sample by
 * 60s widens its bucket to ~60ms.) The min value of an exch-based segment
 * bounds (clock skew + minimum transit) for the report.
 *
 * <p><b>What gets recorded.</b> Catchup-flagged events (startup replay of the
 * retained queue) are never recorded, and recording only begins
 * {@code warmupMs} after the first live event — startup replay flooded the
 * cumulative tail with multi-second "latencies" that were really replay lag,
 * and cumulative histograms never forget.
 *
 * <p>Single writer ({@link #record} on the OrderWriterHandler thread),
 * single reader (the stats logger thread) — the Recorder pattern.
 * {@link #writeReport} must only run after both have stopped.
 */
public final class StrategyLatency {

    private static final Logger log = LoggerFactory.getLogger(StrategyLatency.class);

    private static final long HIGHEST_TRACKABLE_NANOS = 60_000_000_000L;
    private static final int SIGNIFICANT_DIGITS = 3;

    private final Segment pubToConsume = new Segment("pub->consume (cross-process)");
    private final Segment consumeToPlaced = new Segment("consume->placed (in-process)");
    private final Segment recvToPlaced = new Segment("ws-recv->placed (full chain, same-host clock)");
    private final Segment exchToPlaced = new Segment("exch->placed (e2e, signed, incl. clock skew)");

    /** Docs older than this at consume time are catchup replay, not live flow — excluded. */
    private final long maxDocAgeNanos;
    /** Live events inside this window after the first live event are JIT/page-cache warmup — excluded. */
    private final long warmupNanos;

    private long firstLiveNanos;
    private boolean recording;

    public StrategyLatency(long maxDocAgeMs, long warmupMs) {
        this.maxDocAgeNanos = maxDocAgeMs * 1_000_000L;
        this.warmupNanos = warmupMs * 1_000_000L;
    }

    public void record(StrategyEvent e) {
        // Startup replay: updates the book but says nothing about live latency.
        if (e.catchup) {
            return;
        }
        if (!recording) {
            if (firstLiveNanos == 0L) {
                firstLiveNanos = e.consumeNanos;
            }
            if (e.consumeNanos - firstLiveNanos < warmupNanos) {
                return;
            }
            recording = true;
            log.info("Latency warmup complete ({} ms) — recording starts now", warmupNanos / 1_000_000L);
        }
        // Live-period stall guard (WS outage replay etc.): stale docs still
        // update the book but would poison the epoch-based segments.
        if (e.delta.pubTsEpochNanos > 0 && e.consumeEpochNanos > 0
                && e.consumeEpochNanos - e.delta.pubTsEpochNanos > maxDocAgeNanos) {
            return;
        }
        if (e.consumeEpochNanos > 0 && e.delta.pubTsEpochNanos > 0) {
            pubToConsume.record(e.consumeEpochNanos - e.delta.pubTsEpochNanos);
        }
        boolean inProc = e.placedNanos != 0 && e.consumeNanos != 0;
        if (inProc) {
            consumeToPlaced.record(e.placedNanos - e.consumeNanos);
        }
        if (inProc && e.delta.recvTsEpochNanos > 0 && e.consumeEpochNanos > 0) {
            // The headline number: Process A's WS receive to this process's
            // order-write point. recvTs and consumeEpoch come from the same
            // physical clock (same host), so unlike the exchange segment
            // there is no cross-host skew — only the two Instant.now() reads.
            long recvToConsume = e.consumeEpochNanos - e.delta.recvTsEpochNanos;
            recvToPlaced.record(recvToConsume + (e.placedNanos - e.consumeNanos));
        }
        if (inProc && e.delta.exchTsEpochNanos > 0 && e.consumeEpochNanos > 0) {
            // exch->placed = (exch->consume, epoch) + (consume->placed, mono).
            long exchToConsume = e.consumeEpochNanos - e.delta.exchTsEpochNanos;
            exchToPlaced.record(exchToConsume + (e.placedNanos - e.consumeNanos));
        }
    }

    public List<String> summaryLines() {
        List<String> lines = new ArrayList<>(4);
        lines.add(pubToConsume.describeInterval());
        lines.add(consumeToPlaced.describeInterval());
        lines.add(recvToPlaced.describeInterval());
        lines.add(exchToPlaced.describeInterval());
        return lines;
    }

    /** Whole-run cumulative — what the latency report quotes. */
    public List<String> cumulativeSummaryLines() {
        List<String> lines = new ArrayList<>(4);
        lines.add(pubToConsume.describeCumulative());
        lines.add(consumeToPlaced.describeCumulative());
        lines.add(recvToPlaced.describeCumulative());
        lines.add(exchToPlaced.describeCumulative());
        return lines;
    }

    /**
     * Write the whole-run report (summary + percentile table per segment).
     * Drains the recorders, so call either from the stats thread itself (the
     * designated single reader) or after pipeline and stats have stopped.
     */
    public void writeReport(Path file) throws IOException {
        Path dir = file.toAbsolutePath().getParent();
        if (dir != null) {
            Files.createDirectories(dir);
        }
        try (BufferedWriter w = Files.newBufferedWriter(file, StandardCharsets.UTF_8)) {
            w.write("Strategy+Execution latency report — " + Instant.now());
            w.newLine();
            w.write("Values are signed. Epoch-based segments include cross-clock skew;");
            w.newLine();
            w.write("a negative min on the exch segment bounds (clock skew + min transit).");
            w.newLine();
            w.write("Startup replay and the first warmup window are excluded.");
            w.newLine();
            for (Segment s : new Segment[]{pubToConsume, consumeToPlaced, recvToPlaced, exchToPlaced}) {
                w.newLine();
                s.writeReportBlock(w);
            }
        }
    }

    /**
     * One latency segment, recorded signed as a pair of HdrHistograms:
     * {@code pos} holds values ≥ 0, {@code neg} holds magnitudes of negative
     * values. Percentiles are computed over the merged distribution by rank.
     */
    private static final class Segment {
        private static final double[] REPORT_PERCENTILES =
                {0.0, 10.0, 25.0, 50.0, 75.0, 90.0, 99.0, 99.9, 99.99, 100.0};

        private final String name;
        private final Recorder posRecorder = new Recorder(HIGHEST_TRACKABLE_NANOS, SIGNIFICANT_DIGITS);
        private final Recorder negRecorder = new Recorder(HIGHEST_TRACKABLE_NANOS, SIGNIFICANT_DIGITS);
        private Histogram posInterval;
        private Histogram negInterval;
        private final Histogram posCum = new Histogram(HIGHEST_TRACKABLE_NANOS, SIGNIFICANT_DIGITS);
        private final Histogram negCum = new Histogram(HIGHEST_TRACKABLE_NANOS, SIGNIFICANT_DIGITS);

        Segment(String name) {
            this.name = name;
        }

        void record(long nanos) {
            if (nanos >= 0) {
                posRecorder.recordValue(Math.min(nanos, HIGHEST_TRACKABLE_NANOS));
            } else {
                negRecorder.recordValue(Math.min(-nanos, HIGHEST_TRACKABLE_NANOS));
            }
        }

        String describeInterval() {
            drainInterval();
            return describe(name, negInterval, posInterval);
        }

        String describeCumulative() {
            drainInterval();
            return describe(name, negCum, posCum);
        }

        private void drainInterval() {
            posInterval = posRecorder.getIntervalHistogram(posInterval);
            negInterval = negRecorder.getIntervalHistogram(negInterval);
            posCum.add(posInterval);
            negCum.add(negInterval);
        }

        void writeReportBlock(BufferedWriter w) throws IOException {
            drainInterval();
            w.write(describe(name, negCum, posCum));
            w.newLine();
            if (negCum.getTotalCount() + posCum.getTotalCount() == 0) {
                return;
            }
            for (double p : REPORT_PERCENTILES) {
                w.write(String.format("  %7.2f%%  %14.1fus", p, usAt(negCum, posCum, p)));
                w.newLine();
            }
        }

        private static String describe(String name, Histogram neg, Histogram pos) {
            long n = neg.getTotalCount() + pos.getTotalCount();
            if (n == 0) {
                return name + ": n=0";
            }
            return String.format("%s: n=%d min=%.1fus p50=%.1fus p99=%.1fus p99.9=%.1fus max=%.1fus",
                    name, n,
                    minUs(neg, pos),
                    usAt(neg, pos, 50.0),
                    usAt(neg, pos, 99.0),
                    usAt(neg, pos, 99.9),
                    maxUs(neg, pos));
        }

        /** Value at percentile {@code pct} of the merged signed distribution, in µs. */
        private static double usAt(Histogram neg, Histogram pos, double pct) {
            long nNeg = neg.getTotalCount();
            long nPos = pos.getTotalCount();
            if (nNeg == 0) {
                return pos.getValueAtPercentile(pct) / 1000.0;
            }
            if (nPos == 0) {
                // Ascending actual order = descending magnitude order.
                return -neg.getValueAtPercentile(100.0 - pct) / 1000.0;
            }
            long n = nNeg + nPos;
            // Rank of the requested percentile in ascending signed order.
            long rank = Math.min(n - 1, (long) Math.floor(pct / 100.0 * n));
            if (rank < nNeg) {
                // rank 0 = most negative = largest magnitude.
                double magPct = 100.0 * (nNeg - rank) / nNeg;
                return -neg.getValueAtPercentile(magPct) / 1000.0;
            }
            double posPct = 100.0 * (rank - nNeg + 1) / nPos;
            return pos.getValueAtPercentile(posPct) / 1000.0;
        }

        private static double minUs(Histogram neg, Histogram pos) {
            if (neg.getTotalCount() > 0) {
                return -neg.getMaxValue() / 1000.0;
            }
            return pos.getMinValue() / 1000.0;
        }

        private static double maxUs(Histogram neg, Histogram pos) {
            if (pos.getTotalCount() > 0) {
                return pos.getMaxValue() / 1000.0;
            }
            return -neg.getMinValue() / 1000.0;
        }
    }
}
