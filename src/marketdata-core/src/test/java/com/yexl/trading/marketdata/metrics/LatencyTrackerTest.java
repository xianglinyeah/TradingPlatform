package com.yexl.trading.marketdata.metrics;

import com.yexl.trading.marketdata.model.MarketDataEvent;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

class LatencyTrackerTest {

    @Test
    void recordIgnoresEventsWithoutReceiveTimestamp() {
        LatencyTracker tracker = new LatencyTracker();
        MarketDataEvent e = new MarketDataEvent();
        // receiveTimeNanos left at 0 => record() is a no-op

        tracker.record(e);

        List<String> lines = tracker.summaryLines();
        assertTrue(lines.stream().allMatch(l -> l.endsWith("n=0")));
    }

    @Test
    void recordPopulatesAllInProcessSegmentsForAFullyStampedEvent() {
        LatencyTracker tracker = new LatencyTracker();
        MarketDataEvent e = new MarketDataEvent();
        e.receiveTimeNanos = 1_000_000L;
        e.receiveTimeEpochNanos = 5_000_000_000L;
        e.exchangeTsNanos = 4_900_000_000L; // 100ms before receive, epoch domain
        e.parsedNanos = 1_100_000L;
        e.bookAppliedNanos = 1_300_000L;
        e.publishedNanos = 1_400_000L;

        tracker.record(e);
        tracker.recordPublish(e);

        List<String> interval = tracker.summaryLines();
        // exch->recv, recv->parse, parse->apply, recv->apply, apply->publish, recv->publish
        assertTrue(interval.size() == 6);
        for (String line : interval) {
            assertTrue(line.contains("n=1"), () -> "expected n=1 in: " + line);
        }

        List<String> cumulative = tracker.cumulativeSummaryLines();
        assertTrue(cumulative.size() == 6);
        for (String line : cumulative) {
            assertTrue(line.contains("n=1"), () -> "expected n=1 in: " + line);
        }
    }

    @Test
    void cumulativeAccumulatesAcrossMultipleIntervalDrains() {
        LatencyTracker tracker = new LatencyTracker();
        for (int i = 0; i < 3; i++) {
            MarketDataEvent e = new MarketDataEvent();
            e.receiveTimeNanos = 1_000_000L;
            e.parsedNanos = 1_050_000L;
            e.bookAppliedNanos = 1_100_000L;
            tracker.record(e);
            tracker.summaryLines(); // drains interval into cumulative each time
        }

        List<String> cumulative = tracker.cumulativeSummaryLines();
        String receiveToApply = cumulative.get(3); // recv->apply is index 3
        assertTrue(receiveToApply.contains("n=3"), () -> "expected n=3 in: " + receiveToApply);
    }
}
