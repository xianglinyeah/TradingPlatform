package com.yexl.trading.strategy.handlers;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.strategy.metrics.StrategyLatency;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Pipeline stage 3 — "order placement" stub: risk-approved signals are
 * written as JSON lines to a timestamped file. Structurally this is where a
 * venue adapter (FIX/WS/REST) plugs in later; the handler seam is already
 * the right shape.
 *
 * <p>Also the end of the measured pipeline: stamps {@code placedNanos} and
 * records all latency segments (this is the single-threaded tail of the
 * chain, so recording here is race-free for the in-process segments).
 */
public final class OrderWriterHandler implements EventHandler<StrategyEvent>, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(OrderWriterHandler.class);

    private final BufferedWriter out;
    private final Path file;
    private final StrategyLatency latency;
    private final AtomicLong ordersWritten = new AtomicLong();
    private long orderId;

    public OrderWriterHandler(StrategyConfig config, StrategyLatency latency) throws IOException {
        Path dir = Path.of(config.ordersDir);
        Files.createDirectories(dir);
        String stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
        this.file = dir.resolve("orders-" + stamp + ".jsonl");
        this.out = Files.newBufferedWriter(file, StandardCharsets.UTF_8);
        this.latency = latency;
        log.info("Order writer opened: {}", file.toAbsolutePath());
    }

    private long arbId;

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        // Latency is recorded for every md doc (not only signals) so the
        // md-consume segments aren't biased toward signal-bearing events.
        if (event.arbSignal && event.riskApproved) {
            writeArbOrders(event);
        } else if (event.signal != StrategyEvent.SIGNAL_NONE && event.riskApproved) {
            writeOrder(event);
        }
        event.placedNanos = System.nanoTime();
        latency.record(event);
    }

    /** Two lines sharing an arbId — one order pair, atomically approved. */
    private void writeArbOrders(StrategyEvent e) {
        long pairId = arbId++;
        writeArbLeg(e, pairId, e.arbBuyLeg, "BUY");
        writeArbLeg(e, pairId, e.arbSellLeg, "SELL");
    }

    private void writeArbLeg(StrategyEvent e, long pairId, StrategyEvent.Leg leg, String side) {
        try {
            leg.orderId = orderId;
            out.write("{\"id\":" + (orderId++)
                    + ",\"arbId\":" + pairId
                    + ",\"symbol\":\"" + e.arbSymbol + '"'
                    + ",\"tsEpochNanos\":" + e.consumeEpochNanos
                    + ",\"venue\":\"" + leg.venue + '"'
                    + ",\"product\":\"" + leg.productId + '"'
                    + ",\"side\":\"" + side + '"'
                    + ",\"qty\":\"" + leg.qty.toPlainString() + '"'
                    + ",\"price\":\"" + leg.touchPrice + '"'
                    + ",\"devBps\":" + String.format("%.4f", e.arbDevBps)
                    + ",\"emaBps\":" + String.format("%.4f", e.arbEmaBps)
                    + "}");
            out.newLine();
            out.flush();
            ordersWritten.incrementAndGet();
        } catch (IOException ex) {
            log.error("Arb order write failed", ex);
        }
    }

    private void writeOrder(StrategyEvent e) {
        try {
            e.orderId = orderId;
            // Hand-built JSON: all values are numbers/enum-like strings under
            // our control, nothing needs escaping.
            out.write("{\"id\":" + (orderId++)
                    + ",\"tsEpochNanos\":" + e.consumeEpochNanos
                    + ",\"venue\":\"" + e.delta.venue + '"'
                    + ",\"product\":\"" + e.delta.productId + '"'
                    + ",\"side\":\"" + (e.signal == StrategyEvent.SIGNAL_BUY ? "BUY" : "SELL") + '"'
                    + ",\"qty\":\"" + e.orderQty.toPlainString() + '"'
                    + ",\"price\":\"" + e.touchPrice + '"'
                    + ",\"imbalance\":" + String.format("%.4f", e.imbalance)
                    + ",\"srcPseq\":" + e.delta.pseq
                    + ",\"exchTs\":" + e.delta.exchTsEpochNanos
                    + ",\"pubTs\":" + e.delta.pubTsEpochNanos
                    + "}");
            out.newLine();
            // Order rate is low (cooldown-gated); flush per order so the
            // file is always inspectable and nothing is lost on kill.
            out.flush();
            ordersWritten.incrementAndGet();
        } catch (IOException ex) {
            log.error("Order write failed", ex);
        }
    }

    public long ordersWrittenCount() {
        return ordersWritten.get();
    }

    @Override
    public void close() {
        try {
            out.close();
        } catch (IOException ignored) { }
        log.info("Order writer closed: {} orders in {}", ordersWritten.get(), file.toAbsolutePath());
    }
}
