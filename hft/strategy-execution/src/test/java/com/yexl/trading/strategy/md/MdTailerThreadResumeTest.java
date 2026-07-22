package com.yexl.trading.strategy.md;

import com.lmax.disruptor.RingBuffer;
import com.lmax.disruptor.YieldingWaitStrategy;
import com.yexl.trading.marketdata.wire.MdDelta;
import com.yexl.trading.marketdata.wire.MdWireCodec;
import com.yexl.trading.strategy.StrategyEvent;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptAppender;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** End-to-end check of the fast-resume path: a second tailer seeded with the
 * first one's last-processed queue index must consume the remaining docs
 * exactly once each — no gap, no duplicate. */
class MdTailerThreadResumeTest {

    private MdTailerThread tailer;

    @AfterEach
    void tearDown() throws InterruptedException {
        if (tailer != null) {
            tailer.shutdown();
            tailer.join(2000);
        }
    }

    private static void writeDocs(String queueDir, int count, String productId) {
        try (ChronicleQueue q = ChronicleQueue.singleBuilder(queueDir).build()) {
            ExcerptAppender app = q.createAppender();
            for (int i = 0; i < count; i++) {
                MdDelta d = new MdDelta();
                d.venue = "COINBASE";
                d.productId = productId;
                d.snapshot = i == 0;
                d.pseq = i;
                d.recvTsEpochNanos = 1_000_000_000L + i;
                d.pubTsEpochNanos = d.recvTsEpochNanos;
                d.prepareLevels(1);
                d.setLevel(0, MdDelta.SIDE_BID, "100." + i, "1");
                app.writeDocument(w -> MdWireCodec.write(w, d));
            }
        }
    }

    @Test
    void resumeIndexConsumesRemainingDocsExactlyOnce(@TempDir Path tmp) throws Exception {
        String queueDir = tmp.resolve("q").toString();
        writeDocs(queueDir, 10, "BTC-USD");

        // First pass: consume from start, capture the queueIndex of doc #4 (pseq==4).
        RingBuffer<StrategyEvent> ring1 = RingBuffer.createSingleProducer(
                StrategyEvent.FACTORY, 64, new YieldingWaitStrategy());
        CopyOnWriteArrayList<Long> seenPseq1 = new CopyOnWriteArrayList<>();
        long[] checkpointIndex = {-1L};
        tailer = new MdTailerThread(List.of(queueDir), "start", ring1, null);
        // Poll consumer: read whatever the tailer has published so far via the ring's cursor.
        long nextRead = 0;
        tailer.start();
        long deadline = System.currentTimeMillis() + 3000;
        while (seenPseq1.size() < 5 && System.currentTimeMillis() < deadline) {
            long cursor = ring1.getCursor();
            while (nextRead <= cursor) {
                StrategyEvent e = ring1.get(nextRead);
                seenPseq1.add(e.delta.pseq);
                if (e.delta.pseq == 4L) {
                    checkpointIndex[0] = e.queueIndex;
                }
                nextRead++;
            }
        }
        tailer.shutdown();
        tailer.join(2000);
        tailer = null;

        assertEquals(List.of(0L, 1L, 2L, 3L, 4L), seenPseq1);
        assertTrue(checkpointIndex[0] >= 0, "checkpoint index should have been captured");

        // Second pass: resume from checkpointIndex+1 -- must get pseq 5..9, nothing before.
        RingBuffer<StrategyEvent> ring2 = RingBuffer.createSingleProducer(
                StrategyEvent.FACTORY, 64, new YieldingWaitStrategy());
        CopyOnWriteArrayList<Long> seenPseq2 = new CopyOnWriteArrayList<>();
        tailer = new MdTailerThread(List.of(queueDir), "start", ring2, null, checkpointIndex[0] + 1);
        tailer.start();
        long nextRead2 = 0;
        long deadline2 = System.currentTimeMillis() + 3000;
        while (seenPseq2.size() < 5 && System.currentTimeMillis() < deadline2) {
            long cursor = ring2.getCursor();
            while (nextRead2 <= cursor) {
                seenPseq2.add(ring2.get(nextRead2).delta.pseq);
                nextRead2++;
            }
        }

        assertEquals(List.of(5L, 6L, 7L, 8L, 9L), seenPseq2);
    }
}
