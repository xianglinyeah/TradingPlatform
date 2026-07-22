package com.yexl.trading.coinbase.recording;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Optional raw-frame recorder: appends every inbound WS text frame as one
 * JSON line to a timestamped file, for later replay through the
 * ParseHandler/OrderBookHandler pipeline (gap-injection tests, debugging).
 *
 * <p>Never blocks the caller: {@link #offer(String)} is a bounded-queue
 * {@code offer}; a dedicated writer thread does the file I/O. If the queue is
 * full (disk stalled), frames are dropped from the <b>recording</b> (counted
 * and logged on close) — market data processing itself is unaffected.
 */
public final class FrameRecorder implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(FrameRecorder.class);
    private static final int QUEUE_CAPACITY = 65_536;
    private static final int FLUSH_EVERY = 500;

    private final BlockingQueue<String> queue = new ArrayBlockingQueue<>(QUEUE_CAPACITY);
    private final AtomicLong written = new AtomicLong();
    private final AtomicLong dropped = new AtomicLong();
    private final Path file;
    private final Thread writerThread;
    private volatile boolean closed;

    public FrameRecorder(String dir) throws IOException {
        Path dirPath = Path.of(dir);
        Files.createDirectories(dirPath);
        String stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
        this.file = dirPath.resolve("frames-" + stamp + ".jsonl");
        this.writerThread = new Thread(this::writeLoop, "frame-recorder");
        this.writerThread.setDaemon(true);
        this.writerThread.start();
        log.info("FrameRecorder started: {}", file.toAbsolutePath());
    }

    /** Non-blocking; called from the WS I/O thread. */
    public void offer(String rawJson) {
        if (closed) {
            return;
        }
        if (!queue.offer(rawJson)) {
            dropped.incrementAndGet();
        }
    }

    private void writeLoop() {
        try (BufferedWriter out = Files.newBufferedWriter(file, StandardCharsets.UTF_8)) {
            int sinceFlush = 0;
            while (!closed || !queue.isEmpty()) {
                String frame = queue.poll(200, TimeUnit.MILLISECONDS);
                if (frame == null) {
                    if (sinceFlush > 0) {
                        out.flush();
                        sinceFlush = 0;
                    }
                    continue;
                }
                // One frame per line. Raw control chars are invalid inside
                // JSON string literals, so any newlines present are
                // insignificant inter-token whitespace — safe to strip.
                if (frame.indexOf('\n') >= 0 || frame.indexOf('\r') >= 0) {
                    frame = frame.replace("\n", "").replace("\r", "");
                }
                out.write(frame);
                out.newLine();
                written.incrementAndGet();
                if (++sinceFlush >= FLUSH_EVERY) {
                    out.flush();
                    sinceFlush = 0;
                }
            }
            out.flush();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (IOException e) {
            log.error("FrameRecorder writer failed; recording stopped ({} frames written)", written.get(), e);
        }
    }

    @Override
    public void close() {
        closed = true;
        try {
            writerThread.join(3_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        log.info("FrameRecorder closed: {} frames written, {} dropped, file={}",
                written.get(), dropped.get(), file.toAbsolutePath());
    }
}
