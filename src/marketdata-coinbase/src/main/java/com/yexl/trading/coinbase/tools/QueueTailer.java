package com.yexl.trading.coinbase.tools;

import com.yexl.trading.marketdata.wire.MdDelta;
import com.yexl.trading.marketdata.wire.MdWireCodec;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptTailer;
import org.HdrHistogram.Histogram;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * Minimal cross-process verification consumer for the market data queue
 * (Step 4 acceptance tool). Decodes via the shared {@link MdWireCodec}.
 *
 * <p>Tails the venue queue from the end (new documents only) and every
 * 5 seconds prints: document count, level counts, best bid/ask reconstructed
 * from the stream (top-of-book only — proves the deltas are usable
 * downstream), pseq continuity, and the publish→tail latency distribution
 * (epoch-clock based, same-host).
 *
 * <p>Run from the shaded jar (module flags come from the manifest only for
 * {@code java -jar}, so pass them explicitly here):
 * <pre>
 * java --add-exports=java.base/jdk.internal.ref=ALL-UNNAMED \
 *      --add-exports=java.base/sun.nio.ch=ALL-UNNAMED \
 *      --add-opens=java.base/sun.nio.ch=ALL-UNNAMED \
 *      --add-opens=java.base/java.lang=ALL-UNNAMED \
 *      --add-opens=java.base/java.lang.reflect=ALL-UNNAMED \
 *      --add-opens=java.base/java.io=ALL-UNNAMED \
 *      --add-opens=java.base/java.util=ALL-UNNAMED \
 *      -cp marketdata-coinbase.jar \
 *      com.yexl.trading.coinbase.tools.QueueTailer queues/md-coinbase
 * </pre>
 */
public final class QueueTailer {

    public static void main(String[] args) throws Exception {
        System.setProperty("chronicle.analytics.disable", "true");
        String dir = args.length > 0 ? args[0] : "queues/md-coinbase";

        try (ChronicleQueue queue = ChronicleQueue.singleBuilder(dir).build()) {
            ExcerptTailer tailer = queue.createTailer().toEnd();
            System.out.println("Tailing " + queue.file().getAbsolutePath() + " from end...");

            MdDelta delta = new MdDelta();
            Histogram pubToTail = new Histogram(10_000_000_000L, 3);
            long[] docs = {0};
            long[] snapshots = {0};
            long[] levels = {0};
            long[] lastPseq = {-1};
            long[] seqGaps = {0};
            BigDecimal[] bestBid = {null};
            BigDecimal[] bestAsk = {null};

            long lastReport = System.currentTimeMillis();
            while (true) {
                boolean read = tailer.readDocument(w -> {
                    MdWireCodec.read(w, delta);
                    if (delta.schemaVersion != MdWireCodec.SCHEMA_VERSION) {
                        System.err.println("Unknown schema version " + delta.schemaVersion + " — skipping");
                        return;
                    }

                    Instant now = Instant.now();
                    long nowEpochNanos = now.getEpochSecond() * 1_000_000_000L + now.getNano();
                    long lat = nowEpochNanos - delta.pubTsEpochNanos;
                    pubToTail.recordValue(Math.min(Math.max(lat, 0), 10_000_000_000L));

                    if (delta.snapshot) {
                        snapshots[0]++;
                        bestBid[0] = null;
                        bestAsk[0] = null;
                    }
                    if (lastPseq[0] >= 0 && delta.pseq != lastPseq[0] + 1) {
                        seqGaps[0]++;
                    }
                    lastPseq[0] = delta.pseq;

                    for (int i = 0; i < delta.levelCount; i++) {
                        levels[0]++;
                        // Top-of-book tracking only — enough to prove the
                        // stream is usable without keeping a full book here.
                        BigDecimal price = new BigDecimal(delta.prices[i]);
                        boolean removed = new BigDecimal(delta.qtys[i]).signum() == 0;
                        if (delta.sides[i] == MdDelta.SIDE_BID) {
                            if (removed) {
                                if (price.equals(bestBid[0])) bestBid[0] = null;
                            } else if (bestBid[0] == null || price.compareTo(bestBid[0]) > 0) {
                                bestBid[0] = price;
                            }
                        } else {
                            if (removed) {
                                if (price.equals(bestAsk[0])) bestAsk[0] = null;
                            } else if (bestAsk[0] == null || price.compareTo(bestAsk[0]) < 0) {
                                bestAsk[0] = price;
                            }
                        }
                    }
                    docs[0]++;
                });

                if (!read) {
                    Thread.onSpinWait();
                }

                long nowMs = System.currentTimeMillis();
                if (nowMs - lastReport >= 5_000) {
                    System.out.printf(
                            "docs=%d (snap=%d) levels=%d seqGaps=%d bestBid=%s bestAsk=%s | pub->tail p50=%.1fus p99=%.1fus max=%.1fus%n",
                            docs[0], snapshots[0], levels[0], seqGaps[0],
                            bestBid[0], bestAsk[0],
                            pubToTail.getValueAtPercentile(50.0) / 1000.0,
                            pubToTail.getValueAtPercentile(99.0) / 1000.0,
                            pubToTail.getMaxValue() / 1000.0);
                    pubToTail.reset();
                    lastReport = nowMs;
                }
            }
        }
    }
}
