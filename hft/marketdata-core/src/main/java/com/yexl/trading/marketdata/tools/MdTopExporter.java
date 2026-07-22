package com.yexl.trading.marketdata.tools;

import com.yexl.trading.marketdata.book.TopBook;
import com.yexl.trading.marketdata.wire.MdDelta;
import com.yexl.trading.marketdata.wire.MdWireCodec;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptTailer;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * Offline exporter: replay a whole md queue directory and emit the
 * top-of-book stream as JSONL, one row per best-bid/ask <em>price</em>
 * change per product. Feeds the ClickHouse {@code hft.md_top} table
 * (see scripts/reporting/schema.sql) — the md half of the ASOF-join
 * analytics (slippage, mark-to-market PnL).
 *
 * <p>Price-change-only emission is lossless for mid-based analytics
 * (the mid can only move when a best price moves) and roughly an order
 * of magnitude smaller than one row per delta doc. The qty fields carry
 * whatever was displayed at the moment of the price change.
 *
 * <p>Reads from the start and exits at end-of-queue — this is a batch
 * tool for static/archived queues, not a live tailer; it never touches
 * the hot path.
 *
 * <p>With an optional third argument it also emits per-second flow/latency
 * aggregates in the same replay pass (one row per venue|product|second):
 * doc/level/snapshot counts, publisher-sequence gaps, and the recv→pub /
 * exch→recv latency distribution — feeds {@code hft.md_stats} for the
 * md-flow and latency dashboards. exch→recv is signed epoch math and
 * includes cross-clock skew; recv→pub is same-host and skew-free.
 *
 * <p>Run from a venue shaded jar (Chronicle needs the module flags):
 * <pre>
 * java --add-exports=java.base/jdk.internal.ref=ALL-UNNAMED \
 *      --add-exports=java.base/sun.nio.ch=ALL-UNNAMED \
 *      --add-opens=java.base/sun.nio.ch=ALL-UNNAMED \
 *      --add-opens=java.base/java.lang=ALL-UNNAMED \
 *      --add-opens=java.base/java.lang.reflect=ALL-UNNAMED \
 *      --add-opens=java.base/java.io=ALL-UNNAMED \
 *      --add-opens=java.base/java.util=ALL-UNNAMED \
 *      -cp marketdata-coinbase.jar \
 *      com.yexl.trading.marketdata.tools.MdTopExporter <queueDir> <top.jsonl> [stats.jsonl]
 * </pre>
 */
public final class MdTopExporter {

    /** Last emitted top for one product — dedup state. */
    private static final class LastTop {
        BigDecimal bid;
        BigDecimal ask;
    }

    /** One venue|product's accumulating per-second stats bucket. */
    private static final class StatsBucket {
        long second = Long.MIN_VALUE;
        long docs;
        long levels;
        long snapshots;
        long seqGaps;
        final java.util.ArrayList<Long> recvToPubUs = new java.util.ArrayList<>();
        final java.util.ArrayList<Long> exchToRecvUs = new java.util.ArrayList<>();

        void reset(long newSecond) {
            second = newSecond;
            docs = 0;
            levels = 0;
            snapshots = 0;
            seqGaps = 0;
            recvToPubUs.clear();
            exchToRecvUs.clear();
        }
    }

    private static long percentile(java.util.ArrayList<Long> sorted, double q) {
        int idx = (int) Math.ceil(q * sorted.size()) - 1;
        return sorted.get(Math.max(0, Math.min(idx, sorted.size() - 1)));
    }

    private static void flushStats(BufferedWriter statsOut, String key, StatsBucket b) throws IOException {
        int sep = key.indexOf('|');
        StringBuilder sb = new StringBuilder(256);
        sb.append("{\"venue\":\"").append(key, 0, sep)
          .append("\",\"product\":\"").append(key.substring(sep + 1))
          .append("\",\"tsSec\":").append(b.second)
          .append(",\"docs\":").append(b.docs)
          .append(",\"levels\":").append(b.levels)
          .append(",\"snapshots\":").append(b.snapshots)
          .append(",\"seqGaps\":").append(b.seqGaps);
        if (!b.recvToPubUs.isEmpty()) {
            b.recvToPubUs.sort(null);
            sb.append(",\"recvToPubP50Us\":").append(percentile(b.recvToPubUs, 0.50))
              .append(",\"recvToPubP99Us\":").append(percentile(b.recvToPubUs, 0.99))
              .append(",\"recvToPubMaxUs\":").append(b.recvToPubUs.get(b.recvToPubUs.size() - 1));
        }
        if (!b.exchToRecvUs.isEmpty()) {
            b.exchToRecvUs.sort(null);
            sb.append(",\"exchToRecvP50Us\":").append(percentile(b.exchToRecvUs, 0.50))
              .append(",\"exchToRecvP99Us\":").append(percentile(b.exchToRecvUs, 0.99));
        }
        sb.append("}\n");
        statsOut.write(sb.toString());
    }

    public static void main(String[] args) throws Exception {
        System.setProperty("chronicle.analytics.disable", "true");
        if (args.length < 2) {
            System.err.println("usage: MdTopExporter <queueDir> <top.jsonl> [stats.jsonl]");
            System.exit(2);
        }
        Path queueDir = Path.of(args[0]);
        Path outFile = Path.of(args[1]);
        Path statsFile = args.length > 2 ? Path.of(args[2]) : null;

        Map<String, TopBook> books = new HashMap<>();
        Map<String, LastTop> lastTops = new HashMap<>();
        Map<String, StatsBucket> statsBuckets = new HashMap<>();
        MdDelta delta = new MdDelta();
        long[] docs = {0};
        long[] rows = {0};
        long[] skippedVersion = {0};
        long[] lastPseq = {-1};

        try (ChronicleQueue queue = ChronicleQueue.singleBuilder(queueDir.toString()).build();
             BufferedWriter out = Files.newBufferedWriter(outFile, StandardCharsets.UTF_8);
             BufferedWriter statsOut = statsFile == null
                     ? null : Files.newBufferedWriter(statsFile, StandardCharsets.UTF_8)) {
            ExcerptTailer tailer = queue.createTailer().toStart();
            StringBuilder sb = new StringBuilder(256);

            while (tailer.readDocument(w -> {
                MdWireCodec.read(w, delta);
                if (delta.schemaVersion != MdWireCodec.SCHEMA_VERSION) {
                    skippedVersion[0]++;
                    return;
                }
                docs[0]++;
                String key = delta.venue + "|" + delta.productId;
                TopBook book = books.computeIfAbsent(key, k -> new TopBook());
                book.apply(delta);

                if (statsOut != null) {
                    // pseq is dense per queue (not per product); a backward jump
                    // is a publisher restart (rebase), only forward gaps count.
                    boolean gap = lastPseq[0] >= 0
                            && delta.pseq > lastPseq[0] + 1;
                    lastPseq[0] = delta.pseq;

                    long second = delta.recvTsEpochNanos / 1_000_000_000L;
                    StatsBucket b = statsBuckets.computeIfAbsent(key, k -> new StatsBucket());
                    if (b.second != second) {
                        if (b.second != Long.MIN_VALUE) {
                            try {
                                flushStats(statsOut, key, b);
                            } catch (IOException e) {
                                throw new UncheckedIOException(e);
                            }
                        }
                        b.reset(second);
                    }
                    b.docs++;
                    b.levels += delta.levelCount;
                    if (delta.snapshot) b.snapshots++;
                    if (gap) b.seqGaps++;
                    b.recvToPubUs.add((delta.pubTsEpochNanos - delta.recvTsEpochNanos) / 1_000L);
                    if (delta.exchTsEpochNanos != 0) {
                        b.exchToRecvUs.add((delta.recvTsEpochNanos - delta.exchTsEpochNanos) / 1_000L);
                    }
                }

                BigDecimal bid = book.bestBid();
                BigDecimal ask = book.bestAsk();
                if (bid == null || ask == null) {
                    return;
                }
                LastTop last = lastTops.computeIfAbsent(key, k -> new LastTop());
                if (bid.equals(last.bid) && ask.equals(last.ask)) {
                    return;
                }
                last.bid = bid;
                last.ask = ask;

                sb.setLength(0);
                sb.append("{\"venue\":\"").append(delta.venue)
                  .append("\",\"product\":\"").append(delta.productId)
                  .append("\",\"pseq\":").append(delta.pseq)
                  .append(",\"recvTsEpochNanos\":").append(delta.recvTsEpochNanos)
                  .append(",\"bestBid\":").append(bid.toPlainString())
                  .append(",\"bestAsk\":").append(ask.toPlainString())
                  .append(",\"bidQty\":").append(book.topNBidQty(1))
                  .append(",\"askQty\":").append(book.topNAskQty(1))
                  .append("}\n");
                try {
                    out.write(sb.toString());
                } catch (IOException e) {
                    throw new UncheckedIOException(e);
                }
                rows[0]++;
            })) {
                // keep draining until end of queue
            }

            if (statsOut != null) {
                for (Map.Entry<String, StatsBucket> e : statsBuckets.entrySet()) {
                    if (e.getValue().second != Long.MIN_VALUE) {
                        flushStats(statsOut, e.getKey(), e.getValue());
                    }
                }
            }
        }

        System.err.printf("done: docs=%d rows=%d skippedVersion=%d products=%s -> %s%s%n",
                docs[0], rows[0], skippedVersion[0], books.keySet(), outFile,
                statsFile == null ? "" : " (+stats " + statsFile + ")");
    }
}
