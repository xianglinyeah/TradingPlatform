package com.yexl.backtesting.coinbase.disruptor;

import com.lmax.disruptor.EventHandler;
import com.lmax.disruptor.LifecycleAware;
import com.yexl.backtesting.coinbase.metrics.LatencyTracker;
import com.yexl.backtesting.coinbase.model.BookState;
import com.yexl.backtesting.coinbase.model.BookUpdate;
import com.yexl.backtesting.coinbase.model.MarketDataEvent;
import com.yexl.backtesting.coinbase.model.Side;
import com.yexl.backtesting.coinbase.orderbook.OrderBook;
import com.yexl.backtesting.coinbase.orderbook.OrderBookManager;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptAppender;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Disruptor Stage 4 — publishes normalized L2 deltas to this venue's
 * Chronicle Queue (Process A's downstream exit).
 *
 * <p><b>Message schema v1</b> — one self-describing document per contiguous
 * run of updates sharing (product, snapshot-flag):
 * <pre>
 *   v       int32   schema version (1)
 *   ven     text    venue tag, e.g. "COINBASE"
 *   prd     text    product id, e.g. "BTC-USD"
 *   snap    bool    true = downstream must clear its book and reload from this doc
 *   pseq    int64   publisher-assigned dense sequence — THE continuity check
 *                   for consumers (venue seq is NOT dense here: heartbeats and
 *                   other unpublished channels consume venue sequence numbers)
 *   seq     int64   venue sequence number of the source frame (informational)
 *   exchTs  int64   exchange frame timestamp, epoch nanos (0 if absent)
 *   recvTs  int64   WS receive time, epoch nanos
 *   pubTs   int64   publish time, epoch nanos
 *   n       int32   number of levels that follow
 *   n × { s int8 (0=bid,1=ask), p text (price), q text (qty) }
 * </pre>
 * Prices/quantities travel as decimal strings — exact, venue-agnostic, and
 * downstream chooses its own numeric representation. Only epoch timestamps
 * are published: {@code System.nanoTime()} origins are not comparable across
 * JVMs, so the process-local nano stamps stay in this process's histograms.
 *
 * <p><b>STALE filtering:</b> incremental updates for a product whose local
 * book is not {@code LIVE} are not published — the local book rejected them
 * (see {@link OrderBook#applyUpdate}), and a downstream that applied them
 * would corrupt its replica in exactly the way the STALE machinery exists to
 * prevent. The recovery snapshot that follows resets downstream anyway.
 * Snapshot runs are always published.
 *
 * <p>Threading: the {@link ExcerptAppender} is created in {@link #onStart()}
 * so it is owned by this handler's Disruptor thread (appenders are not
 * thread-safe). {@link #close()} may be called from the shutdown hook thread;
 * closing the queue is thread-safe.
 */
public final class ChroniclePublishHandler
        implements EventHandler<MarketDataEvent>, LifecycleAware, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(ChroniclePublishHandler.class);
    private static final int SCHEMA_VERSION = 1;

    private final ChronicleQueue queue;
    private final String venue;
    private final OrderBookManager bookManager;
    private final LatencyTracker latencyTracker;

    private ExcerptAppender appender;

    /** Dense per-published-document sequence; only ever touched on the handler thread. */
    private long publishSeq;

    private final AtomicLong published = new AtomicLong();
    private final AtomicLong staleSuppressed = new AtomicLong();

    public ChroniclePublishHandler(String queueDir, String venue,
                                   OrderBookManager bookManager, LatencyTracker latencyTracker) {
        this.queue = ChronicleQueue.singleBuilder(queueDir).build();
        this.venue = venue;
        this.bookManager = bookManager;
        this.latencyTracker = latencyTracker;
        log.info("Chronicle queue opened: {}", queue.file().getAbsolutePath());
    }

    @Override
    public void onStart() {
        appender = queue.createAppender();
        log.info("Chronicle appender created on {}", Thread.currentThread().getName());
    }

    @Override
    public void onShutdown() {
        // Queue close happens in close(); nothing thread-affine to release here.
    }

    @Override
    public void onEvent(MarketDataEvent event, long sequence, boolean endOfBatch) {
        switch (event.messageType) {
            case SNAPSHOT, UPDATE -> { }
            default -> { return; }
        }
        BookUpdate[] updates = event.updates;
        int count = event.updateCount;
        if (updates == null || count == 0) {
            return;
        }

        Instant now = Instant.now();
        long pubEpochNanos = now.getEpochSecond() * 1_000_000_000L + now.getNano();
        event.publishedEpochNanos = pubEpochNanos;

        // One document per contiguous (product, snapshot-flag) run. Updates
        // from the same source events[] entry are contiguous in the array, so
        // runs correspond to source entries — no regrouping allocation needed.
        int runStart = 0;
        while (runStart < count) {
            BookUpdate first = updates[runStart];
            int runEnd = runStart + 1;
            while (runEnd < count
                    && updates[runEnd].productId.equals(first.productId)
                    && updates[runEnd].isSnapshot == first.isSnapshot) {
                runEnd++;
            }

            if (shouldPublish(first)) {
                writeRun(event, updates, runStart, runEnd, first, pubEpochNanos);
                published.incrementAndGet();
            } else {
                staleSuppressed.incrementAndGet();
            }
            runStart = runEnd;
        }

        event.publishedNanos = System.nanoTime();
        latencyTracker.recordPublish(event);
    }

    private boolean shouldPublish(BookUpdate first) {
        if (first.isSnapshot) {
            return true;
        }
        OrderBook book = bookManager.get(first.productId);
        return book != null && book.state() == BookState.LIVE;
    }

    private void writeRun(MarketDataEvent event, BookUpdate[] updates,
                          int from, int to, BookUpdate first, long pubEpochNanos) {
        appender.writeDocument(w -> {
            w.write("v").int32(SCHEMA_VERSION);
            w.write("ven").text(venue);
            w.write("prd").text(first.productId);
            w.write("snap").bool(first.isSnapshot);
            w.write("pseq").int64(publishSeq++);
            w.write("seq").int64(event.sequenceNum);
            w.write("exchTs").int64(event.exchangeTsNanos);
            w.write("recvTs").int64(event.receiveTimeEpochNanos);
            w.write("pubTs").int64(pubEpochNanos);
            w.write("n").int32(to - from);
            for (int i = from; i < to; i++) {
                BookUpdate u = updates[i];
                w.write("s").int8(u.side == Side.BID ? (byte) 0 : (byte) 1);
                w.write("p").text(u.price.toPlainString());
                w.write("q").text(u.qty.toPlainString());
            }
        });
    }

    public long publishedCount() {
        return published.get();
    }

    public long staleSuppressedCount() {
        return staleSuppressed.get();
    }

    @Override
    public void close() {
        queue.close();
        log.info("Chronicle queue closed ({} docs published, {} stale-suppressed)",
                published.get(), staleSuppressed.get());
    }
}
