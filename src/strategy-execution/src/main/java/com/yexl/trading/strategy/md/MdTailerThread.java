package com.yexl.trading.strategy.md;

import com.lmax.disruptor.RingBuffer;
import com.yexl.trading.marketdata.wire.MdDelta;
import com.yexl.trading.marketdata.wire.MdWireCodec;
import com.yexl.trading.strategy.StrategyEvent;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptTailer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Thread 1 of the Strategy+Execution process: tails the market-data
 * Chronicle Queue and republishes each decoded document into this process's
 * Disruptor ring buffer.
 *
 * <p>pseq continuity is checked here (the earliest point in this process).
 * A <b>forward</b> jump means documents were lost between publisher and this
 * consumer — with a same-host memory-mapped queue this should never happen,
 * so it's counted and logged loudly. A <b>backward</b> jump means the
 * publisher restarted (each session numbers from 0) and the queue retains
 * documents from multiple sessions; that's rebased silently, mirroring how
 * ParseHandler treats a venue-sequence reset after reconnect.
 *
 * <p>Poll strategy: spin, with periodic {@link Thread#yield()} — deliberately
 * no {@code parkNanos}: Windows timer granularity turns a 100µs park into a
 * 1–15ms sleep, which was measured to push pub→consume p50 to ~8ms. Costs
 * most of a core when idle; acceptable for a hot market-data path.
 */
public final class MdTailerThread extends Thread {

    private static final Logger log = LoggerFactory.getLogger(MdTailerThread.class);
    private static final int SPINS_BEFORE_YIELD = 1_000;

    private final ChronicleQueue queue;
    private final ExcerptTailer tailer;
    private final RingBuffer<StrategyEvent> ringBuffer;
    private final MdDelta scratch = new MdDelta();

    private final AtomicLong consumed = new AtomicLong();
    private final AtomicLong pseqGaps = new AtomicLong();
    private final AtomicLong unknownSchema = new AtomicLong();

    private long lastPseq = -1;
    /** False until the first empty poll — everything before that is startup replay. */
    private boolean caughtUp = false;
    /** Fired once on the first empty poll. In backtest mode (static queue, no writer) this means "history exhausted". */
    private final Runnable onCaughtUp;
    private volatile boolean running = true;

    public MdTailerThread(String queueDir, String tailFrom, RingBuffer<StrategyEvent> ringBuffer,
                          Runnable onCaughtUp) {
        super("md-tailer");
        setDaemon(true);
        this.onCaughtUp = onCaughtUp;
        this.queue = ChronicleQueue.singleBuilder(queueDir).build();
        this.tailer = queue.createTailer();
        if ("end".equals(tailFrom)) {
            tailer.toEnd();
        }
        // "start" = default position: replay the whole retained queue. The
        // day's first snapshot document rebuilds book state from scratch, so
        // a consumer joining mid-day converges to the live book.
        this.ringBuffer = ringBuffer;
        log.info("MdTailerThread: queue={}, from={}", queue.file().getAbsolutePath(), tailFrom);
    }

    @Override
    public void run() {
        int idleSpins = 0;
        while (running) {
            boolean read;
            try {
                read = tailer.readDocument(w -> MdWireCodec.read(w, scratch));
            } catch (Exception e) {
                log.error("Tailer read failed", e);
                continue;
            }
            if (!read) {
                if (!caughtUp) {
                    // First empty poll = reached the live tail. Docs consumed
                    // before this point were replay of the retained queue and
                    // are flagged so latency stats exclude them.
                    caughtUp = true;
                    log.info("Caught up to live queue tail after {} replayed docs", consumed.get());
                    if (onCaughtUp != null) {
                        onCaughtUp.run();
                    }
                }
                if (++idleSpins < SPINS_BEFORE_YIELD) {
                    Thread.onSpinWait();
                } else {
                    Thread.yield();
                    idleSpins = 0;
                }
                continue;
            }
            idleSpins = 0;

            if (scratch.schemaVersion != MdWireCodec.SCHEMA_VERSION) {
                unknownSchema.incrementAndGet();
                continue;
            }
            if (lastPseq >= 0) {
                if (scratch.pseq > lastPseq + 1) {
                    pseqGaps.incrementAndGet();
                    log.error("pseq gap: expected {} got {} — document loss between publisher and consumer",
                            lastPseq + 1, scratch.pseq);
                } else if (scratch.pseq <= lastPseq) {
                    log.info("pseq rebased {} -> {} (publisher session restart in retained queue)",
                            lastPseq, scratch.pseq);
                }
            }
            lastPseq = scratch.pseq;

            long nowNanos = System.nanoTime();
            Instant now = Instant.now();
            long nowEpochNanos = now.getEpochSecond() * 1_000_000_000L + now.getNano();

            // Blocking publish. The source is a durable queue, so unlike the
            // WS thread in Process A there is nothing to lose by waiting:
            // when the pipeline lags (e.g. during replay-from-start catchup),
            // backpressure here just slows the replay down. tryPublishEvent
            // was measured to drop docs during catchup, silently corrupting
            // the book replica.
            ringBuffer.publishEvent((event, seq) -> {
                event.reset();
                event.delta.copyFrom(scratch);
                event.consumeNanos = nowNanos;
                event.consumeEpochNanos = nowEpochNanos;
                event.catchup = !caughtUp;
            });
            consumed.incrementAndGet();
        }
        queue.close();
    }

    public void shutdown() {
        running = false;
    }

    public long consumedCount() {
        return consumed.get();
    }

    public long pseqGapCount() {
        return pseqGaps.get();
    }
}
