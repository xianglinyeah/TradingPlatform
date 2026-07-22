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
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Thread 1 of the Strategy+Execution process: tails one or more per-venue
 * market-data Chronicle Queues and republishes each decoded document into
 * this process's Disruptor ring buffer.
 *
 * <p>Multi-queue merge is by <b>recvTs</b>, not round-robin: each queue has
 * a one-document lookahead buffer, and each iteration publishes the buffered
 * document with the smallest recvTs (all queues stamp recvTs from this same
 * host's clock). This matters for replay: two archived queues with different
 * document densities would drift arbitrarily far apart in stream time under
 * round-robin, silently starving any cross-venue logic. Live, at most one
 * buffer is typically occupied, so a sole available document is published
 * immediately — the merge adds no latency and never waits for a quiet venue.
 * Everything runs on ONE thread, preserving the ring buffer's
 * {@code ProducerType.SINGLE} contract.
 *
 * <p>pseq continuity is checked per queue at read time (each venue publisher
 * numbers its own session). A <b>forward</b> jump means documents were lost
 * between publisher and this consumer — should never happen on a same-host
 * memory-mapped queue, so it's counted and logged loudly. A <b>backward</b>
 * jump means the publisher restarted; rebased silently.
 *
 * <p>Poll strategy: spin, with periodic {@link Thread#yield()} — deliberately
 * no {@code parkNanos}: Windows timer granularity turns a 100µs park into a
 * 1–15ms sleep, which was measured to push pub→consume p50 to ~8ms. Costs
 * most of a core when idle; acceptable for a hot market-data path.
 */
public final class MdTailerThread extends Thread {

    private static final Logger log = LoggerFactory.getLogger(MdTailerThread.class);
    private static final int SPINS_BEFORE_YIELD = 1_000;

    private final ChronicleQueue[] queues;
    private final ExcerptTailer[] tailers;
    private final long[] lastPseq;
    /** One-document lookahead per queue, for the recvTs merge. */
    private final MdDelta[] buffered;
    private final boolean[] hasBuffered;
    /** Chronicle Queue index of each buffered doc (index captured before the read that filled
     * it) — carried onto the published event so a single-queue consumer can checkpoint exactly
     * where it left off. -1 in multi-queue mode (no single well-defined "the" index). */
    private final long[] bufferedIndex;
    private final boolean singleQueue;
    private final RingBuffer<StrategyEvent> ringBuffer;

    private final AtomicLong consumed = new AtomicLong();
    private final AtomicLong pseqGaps = new AtomicLong();
    private final AtomicLong unknownSchema = new AtomicLong();

    /** False until the first pass where every queue is empty and nothing is buffered. */
    private boolean caughtUp = false;
    /** Fired once at that point. In backtest mode (static queues) this means "history exhausted". */
    private final Runnable onCaughtUp;
    private volatile boolean running = true;

    public MdTailerThread(List<String> queueDirs, String tailFrom, RingBuffer<StrategyEvent> ringBuffer,
                          Runnable onCaughtUp) {
        this(queueDirs, tailFrom, ringBuffer, onCaughtUp, -1L);
    }

    /**
     * @param resumeIndex if {@code >= 0} and {@code queueDirs} has exactly one entry, seeks
     *                    directly to this Chronicle Queue index instead of honoring {@code
     *                    tailFrom} — the fast-resume path (see StrategySnapshot), skipping a
     *                    full-day replay. Ignored (falls back to {@code tailFrom}) for
     *                    multi-queue (arb) mode: there's no single well-defined resume point
     *                    across independently-indexed queues.
     */
    public MdTailerThread(List<String> queueDirs, String tailFrom, RingBuffer<StrategyEvent> ringBuffer,
                          Runnable onCaughtUp, long resumeIndex) {
        super("md-tailer");
        setDaemon(true);
        this.onCaughtUp = onCaughtUp;
        int n = queueDirs.size();
        this.singleQueue = n == 1;
        this.queues = new ChronicleQueue[n];
        this.tailers = new ExcerptTailer[n];
        this.lastPseq = new long[n];
        this.buffered = new MdDelta[n];
        this.hasBuffered = new boolean[n];
        this.bufferedIndex = new long[n];
        boolean resuming = singleQueue && resumeIndex >= 0;
        for (int i = 0; i < n; i++) {
            queues[i] = ChronicleQueue.singleBuilder(queueDirs.get(i)).build();
            tailers[i] = queues[i].createTailer();
            lastPseq[i] = -1;
            buffered[i] = new MdDelta();
            if (resuming) {
                tailers[i].moveToIndex(resumeIndex);
                log.info("MdTailerThread: queue[{}]={}, resuming from saved index {} (skipping full replay)",
                        i, queues[i].file().getAbsolutePath(), resumeIndex);
            } else {
                if ("end".equals(tailFrom)) {
                    tailers[i].toEnd();
                }
                // "start" = default position: replay the whole retained queue. The
                // day's first snapshot document rebuilds book state from scratch,
                // so a consumer joining mid-day converges to the live book.
                log.info("MdTailerThread: queue[{}]={}, from={}", i, queues[i].file().getAbsolutePath(), tailFrom);
            }
        }
        this.ringBuffer = ringBuffer;
    }

    @Override
    public void run() {
        int idleSpins = 0;
        while (running) {
            boolean readAny = refillBuffers();

            int pick = -1;
            long best = Long.MAX_VALUE;
            for (int i = 0; i < hasBuffered.length; i++) {
                if (hasBuffered[i] && buffered[i].recvTsEpochNanos < best) {
                    best = buffered[i].recvTsEpochNanos;
                    pick = i;
                }
            }
            if (pick < 0) {
                if (!readAny) {
                    if (!caughtUp) {
                        // Every queue empty, nothing buffered = reached the
                        // live tail everywhere. Docs consumed before this
                        // point were replay of the retained queues.
                        caughtUp = true;
                        log.info("Caught up to live tail on all {} queue(s) after {} replayed docs",
                                tailers.length, consumed.get());
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
                }
                continue;
            }
            idleSpins = 0;
            publish(buffered[pick], bufferedIndex[pick]);
            hasBuffered[pick] = false;
        }
        for (ChronicleQueue q : queues) {
            q.close();
        }
    }

    /** Tries to fill every empty buffer; returns true if any queue yielded a document. */
    private boolean refillBuffers() {
        boolean readAny = false;
        for (int i = 0; i < tailers.length; i++) {
            if (hasBuffered[i]) {
                continue;
            }
            MdDelta target = buffered[i];
            long idx = singleQueue ? tailers[i].index() : -1L;
            boolean read;
            try {
                read = tailers[i].readDocument(w -> MdWireCodec.read(w, target));
            } catch (Exception e) {
                log.error("Tailer read failed (queue {})", i, e);
                continue;
            }
            if (!read) {
                continue;
            }
            readAny = true;
            if (target.schemaVersion != MdWireCodec.SCHEMA_VERSION) {
                unknownSchema.incrementAndGet();
                continue; // dropped; buffer stays empty for the next refill
            }
            checkPseq(i, target.pseq);
            bufferedIndex[i] = idx;
            hasBuffered[i] = true;
        }
        return readAny;
    }

    private void checkPseq(int queueIdx, long pseq) {
        long last = lastPseq[queueIdx];
        if (last >= 0) {
            if (pseq > last + 1) {
                pseqGaps.incrementAndGet();
                log.error("pseq gap (queue {}): expected {} got {} — document loss between publisher and consumer",
                        queueIdx, last + 1, pseq);
            } else if (pseq <= last) {
                log.info("pseq rebased {} -> {} (queue {}: publisher session restart in retained queue)",
                        last, pseq, queueIdx);
            }
        }
        lastPseq[queueIdx] = pseq;
    }

    private void publish(MdDelta doc, long queueIndex) {
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
            event.delta.copyFrom(doc);
            event.consumeNanos = nowNanos;
            event.consumeEpochNanos = nowEpochNanos;
            event.catchup = !caughtUp;
            event.queueIndex = queueIndex;
        });
        consumed.incrementAndGet();
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
