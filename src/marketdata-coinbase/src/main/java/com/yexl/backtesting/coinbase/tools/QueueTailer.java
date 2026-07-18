package com.yexl.backtesting.coinbase.tools;

import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptTailer;
import org.HdrHistogram.Histogram;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * Minimal cross-process verification consumer for the market data queue
 * (Step 4 acceptance tool).
 *
 * <p>Tails the venue queue from the end (new documents only), decodes schema
 * v1, and every 5 seconds prints: document count, per-side level counts, the
 * best bid/ask reconstructed from the stream (top-of-book only — proves the
 * deltas are usable downstream), venue-sequence continuity, and the
 * publish→tail latency distribution (epoch-clock based, same-host).
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
 *      com.yexl.backtesting.coinbase.tools.QueueTailer queues/md-coinbase
 * </pre>
 */
public final class QueueTailer {

    public static void main(String[] args) throws Exception {
        System.setProperty("chronicle.analytics.disable", "true");
        String dir = args.length > 0 ? args[0] : "queues/md-coinbase";

        try (ChronicleQueue queue = ChronicleQueue.singleBuilder(dir).build()) {
            ExcerptTailer tailer = queue.createTailer().toEnd();
            System.out.println("Tailing " + queue.file().getAbsolutePath() + " from end...");

            Histogram pubToTail = new Histogram(10_000_000_000L, 3);
            long[] docs = {0};
            long[] snapshots = {0};
            long[] levels = {0};
            long[] lastSeq = {-1};
            long[] seqGaps = {0};
            BigDecimal[] bestBid = {null};
            BigDecimal[] bestAsk = {null};

            long lastReport = System.currentTimeMillis();
            while (true) {
                boolean read = tailer.readDocument(w -> {
                    int v = w.read("v").int32();
                    if (v != 1) {
                        System.err.println("Unknown schema version " + v + " — skipping");
                        return;
                    }
                    w.read("ven").text();
                    w.read("prd").text();
                    boolean snap = w.read("snap").bool();
                    // pseq is the publisher's dense sequence — the correct
                    // continuity check. Venue seq is NOT dense in this queue
                    // (heartbeats etc. consume venue sequence numbers but are
                    // not published), so it is read and ignored here.
                    long pseq = w.read("pseq").int64();
                    w.read("seq").int64();
                    w.read("exchTs").int64();
                    w.read("recvTs").int64();
                    long pubTs = w.read("pubTs").int64();
                    int n = w.read("n").int32();

                    Instant now = Instant.now();
                    long nowEpochNanos = now.getEpochSecond() * 1_000_000_000L + now.getNano();
                    long lat = nowEpochNanos - pubTs;
                    pubToTail.recordValue(Math.min(Math.max(lat, 0), 10_000_000_000L));

                    if (snap) {
                        snapshots[0]++;
                        bestBid[0] = null;
                        bestAsk[0] = null;
                    }
                    if (lastSeq[0] >= 0 && pseq != lastSeq[0] + 1) {
                        seqGaps[0]++;
                    }
                    lastSeq[0] = pseq;

                    for (int i = 0; i < n; i++) {
                        byte side = w.read("s").int8();
                        String p = w.read("p").text();
                        String q = w.read("q").text();
                        levels[0]++;
                        // Top-of-book tracking only — enough to prove the
                        // stream is usable without keeping a full book here.
                        BigDecimal price = new BigDecimal(p);
                        boolean removed = new BigDecimal(q).signum() == 0;
                        if (side == 0) {
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
