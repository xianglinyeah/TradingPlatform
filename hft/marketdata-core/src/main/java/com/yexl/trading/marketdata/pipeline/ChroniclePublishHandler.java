package com.yexl.trading.marketdata.pipeline;

import com.lmax.disruptor.EventHandler;
import com.lmax.disruptor.LifecycleAware;
import com.yexl.trading.marketdata.metrics.LatencyTracker;
import com.yexl.trading.marketdata.model.BookState;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.model.Side;
import com.yexl.trading.marketdata.book.OrderBook;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.wire.MdDelta;
import com.yexl.trading.marketdata.wire.MdWireCodec;
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
 * <p>Wire format: schema v1, defined once in {@link MdWireCodec} (shared with
 * all consumers — see that class for field-by-field docs). One document per
 * contiguous run of updates sharing (product, snapshot-flag).
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

    private final ChronicleQueue queue;
    private final String venue;
    private final OrderBookManager bookManager;
    private final LatencyTracker latencyTracker;

    private ExcerptAppender appender;

    /** Reused per-document carrier; only ever touched on the handler thread. */
    private final MdDelta delta = new MdDelta();

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
        delta.venue = venue;
        delta.productId = first.productId;
        delta.snapshot = first.isSnapshot;
        delta.pseq = publishSeq++;
        delta.venueSeq = event.sequenceNum;
        delta.exchTsEpochNanos = event.exchangeTsNanos;
        delta.recvTsEpochNanos = event.receiveTimeEpochNanos;
        delta.pubTsEpochNanos = pubEpochNanos;
        delta.prepareLevels(to - from);
        for (int i = from; i < to; i++) {
            BookUpdate u = updates[i];
            delta.setLevel(i - from,
                    u.side == Side.BID ? MdDelta.SIDE_BID : MdDelta.SIDE_ASK,
                    u.price.toPlainString(),
                    u.qty.toPlainString());
        }
        appender.writeDocument(w -> MdWireCodec.write(w, delta));
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
