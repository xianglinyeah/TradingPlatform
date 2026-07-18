package com.yexl.backtesting.coinbase.metrics;

import com.yexl.backtesting.coinbase.model.MarketDataEvent;
import org.HdrHistogram.Histogram;
import org.HdrHistogram.Recorder;

import java.util.ArrayList;
import java.util.List;

/**
 * Per-segment latency histograms for the market data pipeline.
 *
 * <p>Four segments across two clock domains:
 * <ul>
 *   <li>{@code exch->recv} — exchange frame timestamp to WS receive, computed
 *       from <b>wall-clock epoch</b> values on both sides. Includes network
 *       transit, the exchange's own publish delay, and inter-host clock skew
 *       (NTP-bounded) — a trend indicator, not a trustworthy absolute.</li>
 *   <li>{@code recv->parse}, {@code parse->apply}, {@code recv->apply} — all
 *       computed from monotonic {@link System#nanoTime()} stamps within this
 *       process. These are the trustworthy baseline numbers.</li>
 * </ul>
 *
 * <p>Threading: {@link #record(MarketDataEvent)} must only be called from the
 * OrderBookHandler thread (Disruptor guarantees single-threaded handlers);
 * {@link #summaryLines()} is called from the BookMonitor scheduler thread.
 * HdrHistogram's {@link Recorder} is built for exactly this
 * single-writer/single-reader interval-sampling pattern — {@code recordValue}
 * is lock-free and allocation-free on the hot path.
 */
public final class LatencyTracker {

    /** 10s cap; anything above (e.g. a stall while paused in a debugger) is clamped. */
    private static final long HIGHEST_TRACKABLE_NANOS = 10_000_000_000L;
    private static final int SIGNIFICANT_DIGITS = 3;

    private final Segment exchangeToReceive = new Segment("exch->recv (epoch, skew-bounded)");
    private final Segment receiveToParse = new Segment("recv->parse");
    private final Segment parseToApply = new Segment("parse->apply");
    private final Segment receiveToApply = new Segment("recv->apply (total in-process)");
    private final Segment applyToPublish = new Segment("apply->publish (queue write)");
    private final Segment receiveToPublish = new Segment("recv->publish (total incl. queue)");

    /**
     * Record all measurable segments for one fully-processed L2 event.
     * Call once per event, after {@code bookAppliedNanos} is stamped.
     */
    public void record(MarketDataEvent e) {
        if (e.receiveTimeNanos == 0L) {
            return;
        }
        if (e.exchangeTsNanos > 0L && e.receiveTimeEpochNanos > 0L) {
            exchangeToReceive.record(e.receiveTimeEpochNanos - e.exchangeTsNanos);
        }
        if (e.parsedNanos != 0L) {
            receiveToParse.record(e.parsedNanos - e.receiveTimeNanos);
            if (e.bookAppliedNanos != 0L) {
                parseToApply.record(e.bookAppliedNanos - e.parsedNanos);
            }
        }
        if (e.bookAppliedNanos != 0L) {
            receiveToApply.record(e.bookAppliedNanos - e.receiveTimeNanos);
        }
    }

    /**
     * Record the queue-write segments. Called from the ChroniclePublishHandler
     * thread — a different thread than {@link #record(MarketDataEvent)}, which
     * is fine because the two methods touch disjoint Segments and each
     * {@link Recorder} therefore keeps a single writer.
     */
    public void recordPublish(MarketDataEvent e) {
        if (e.publishedNanos == 0L) {
            return;
        }
        if (e.bookAppliedNanos != 0L) {
            applyToPublish.record(e.publishedNanos - e.bookAppliedNanos);
        }
        if (e.receiveTimeNanos != 0L) {
            receiveToPublish.record(e.publishedNanos - e.receiveTimeNanos);
        }
    }

    /**
     * Interval summary (stats since the previous call), one line per segment.
     * Called periodically from the monitor thread.
     */
    public List<String> summaryLines() {
        List<String> lines = new ArrayList<>(6);
        lines.add(exchangeToReceive.describeInterval());
        lines.add(receiveToParse.describeInterval());
        lines.add(parseToApply.describeInterval());
        lines.add(receiveToApply.describeInterval());
        lines.add(applyToPublish.describeInterval());
        lines.add(receiveToPublish.describeInterval());
        return lines;
    }

    private static final class Segment {
        private final String name;
        private final Recorder recorder =
                new Recorder(HIGHEST_TRACKABLE_NANOS, SIGNIFICANT_DIGITS);
        /** Recycled across intervals so the monitor thread doesn't allocate a new histogram each cycle. */
        private Histogram interval;

        Segment(String name) {
            this.name = name;
        }

        void record(long nanos) {
            if (nanos < 0L) {
                // Possible on the epoch segment when clock skew exceeds true
                // latency; clamp rather than throw.
                nanos = 0L;
            } else if (nanos > HIGHEST_TRACKABLE_NANOS) {
                nanos = HIGHEST_TRACKABLE_NANOS;
            }
            recorder.recordValue(nanos);
        }

        String describeInterval() {
            interval = recorder.getIntervalHistogram(interval);
            long n = interval.getTotalCount();
            if (n == 0) {
                return name + ": n=0";
            }
            return String.format("%s: n=%d p50=%.1fus p99=%.1fus p99.9=%.1fus max=%.1fus",
                    name,
                    n,
                    interval.getValueAtPercentile(50.0) / 1000.0,
                    interval.getValueAtPercentile(99.0) / 1000.0,
                    interval.getValueAtPercentile(99.9) / 1000.0,
                    interval.getMaxValue() / 1000.0);
        }
    }
}
