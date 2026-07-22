package com.yexl.trading.strategy.md;

import com.yexl.trading.marketdata.book.TopBook;

import java.io.BufferedWriter;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads/writes the "book + queue position" checkpoint that lets a restart skip
 * the full {@code md.tail-from=start} replay (see MdTailerThread's resume-index
 * constructor). One process (SignalHandler, stage 1) owns writing it on a timer;
 * both SignalHandler and SimFillHandler seed their own separate TopBook replicas
 * from the same loaded snapshot at startup, since they process an identical
 * delta stream and would otherwise reconstruct the same state independently.
 *
 * <p>Format: first line is the Chronicle Queue resume index (see
 * MdTailerThread); every following line is one price level:
 * {@code key<TAB>side<TAB>price<TAB>qty}, key = "venue|product".
 */
public final class BookSnapshotIO {

    private BookSnapshotIO() { }

    public record Loaded(long queueIndex, Map<String, TopBook> booksByKey) { }

    /** Null if no snapshot file exists yet (first-ever run) or it's unreadable/corrupt. */
    public static Loaded load(Path file) {
        if (!Files.exists(file)) {
            return null;
        }
        try {
            List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
            if (lines.isEmpty()) {
                return null;
            }
            long queueIndex = Long.parseLong(lines.get(0).trim());
            Map<String, TopBook> books = new LinkedHashMap<>();
            Map<String, List<TopBook.Level>> bids = new LinkedHashMap<>();
            Map<String, List<TopBook.Level>> asks = new LinkedHashMap<>();
            for (int i = 1; i < lines.size(); i++) {
                String line = lines.get(i);
                if (line.isBlank()) {
                    continue;
                }
                String[] f = line.split("\t");
                if (f.length != 4) {
                    continue;
                }
                String key = f[0];
                TopBook.Level level = new TopBook.Level(new BigDecimal(f[2]), new BigDecimal(f[3]));
                if ("BID".equals(f[1])) {
                    bids.computeIfAbsent(key, k -> new ArrayList<>()).add(level);
                } else {
                    asks.computeIfAbsent(key, k -> new ArrayList<>()).add(level);
                }
            }
            for (String key : bids.keySet()) {
                TopBook b = new TopBook();
                b.restore(bids.getOrDefault(key, List.of()), asks.getOrDefault(key, List.of()));
                books.put(key, b);
            }
            for (String key : asks.keySet()) {
                if (!books.containsKey(key)) {
                    TopBook b = new TopBook();
                    b.restore(List.of(), asks.get(key));
                    books.put(key, b);
                }
            }
            return new Loaded(queueIndex, books);
        } catch (IOException | RuntimeException ex) {
            return null;
        }
    }

    /** Atomic write (temp file + rename), same discipline as the position snapshot. */
    public static void write(Path file, long queueIndex, Map<String, TopBook> booksByKey, int maxLevelsPerSide) {
        Path tmp = file.resolveSibling(file.getFileName() + ".tmp");
        try (BufferedWriter w = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
            w.write(Long.toString(queueIndex));
            w.newLine();
            for (Map.Entry<String, TopBook> e : booksByKey.entrySet()) {
                for (TopBook.Level l : e.getValue().topBids(maxLevelsPerSide)) {
                    w.write(e.getKey() + "\tBID\t" + l.price().toPlainString() + "\t" + l.qty().toPlainString());
                    w.newLine();
                }
                for (TopBook.Level l : e.getValue().topAsks(maxLevelsPerSide)) {
                    w.write(e.getKey() + "\tASK\t" + l.price().toPlainString() + "\t" + l.qty().toPlainString());
                    w.newLine();
                }
            }
            w.flush();
            Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (Throwable ex) {
            // Best-effort periodic checkpoint: a bad iteration must not prevent the next one,
            // and must never take down the caller's hot path.
        }
    }
}
