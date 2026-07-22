package com.yexl.trading.strategy.sim;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.marketdata.book.TopBook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedWriter;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.concurrent.ConcurrentSkipListMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Pipeline tail — simulated execution (paper trading). Risk-approved orders
 * do NOT fill against the book the signal saw: they sit in a pending queue
 * until the market-data stream's own clock ({@code recvTsEpochNanos})
 * advances past signal-time + configured simulated latency, then fill by
 * walking this handler's book replica <b>at that moment</b>. The imbalance
 * signal predicts adverse book moves, so same-tick fills would be
 * systematically optimistic — the delay is the honesty of the simulation.
 * Using the md stream as the clock (no timers) keeps fills deterministic
 * and replayable, which is what lets this same class serve as the backtest
 * fill simulator.
 *
 * <p>Modeled: latency (config), displayed-size haircut (config), taker fee
 * (config). Deliberately NOT modeled: market impact and queue position —
 * legitimate while sim order notional (~$100) is orders of magnitude below
 * top-level depth, and this is a taking strategy with no resting orders.
 *
 * <p>Owns its own book replicas: Disruptor handlers run on separate
 * threads, so sharing SignalHandler's books would be a data race. Each
 * handler applying deltas itself is the idiom.
 */
public final class SimFillHandler implements EventHandler<StrategyEvent>, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(SimFillHandler.class);

    /** Books, trackers and pending orders are all keyed venue|product —
     * BTC-USD@COINBASE and BTC-USDT@OKX are distinct instruments. */
    private final Map<String, TopBook> books = new HashMap<>();
    /** Written by the handler thread, iterated by the stats thread — must be concurrent. */
    private final Map<String, PositionTracker> trackers = new ConcurrentSkipListMap<>();
    /** Min-heap on arrivalTs: cross-venue event interleave makes insertion
     * order only approximately arrival-ordered, and a FIFO would stall due
     * orders behind a not-yet-due head. orderId tie-break keeps replays
     * deterministic. */
    private final PriorityQueue<SimOrder> pending = new PriorityQueue<>(
            Comparator.comparingLong((SimOrder o) -> o.arrivalTs).thenComparingLong(o -> o.orderId));

    private final StrategyConfig config;
    private final long simLatencyNanos;
    /** Per-venue taker fee rates (venues differ: Coinbase ~60bps vs OKX ~10bps). */
    private final Map<String, BigDecimal> feeRates = new HashMap<>();
    private final BigDecimal sizeHaircut;

    private final BufferedWriter out;
    private final Path file;
    private final AtomicLong fillCount = new AtomicLong();
    private final AtomicLong unfilledCount = new AtomicLong();
    private long fillId;

    /** Fixed name (unlike the timestamped sim-fills file) so a fresh process
     * finds the previous one's snapshot — position/PnL is in-memory only
     * otherwise, and every restart would silently reset it to flat. */
    private final Path snapshotFile;
    private final ScheduledExecutorService snapshotScheduler;

    public SimFillHandler(StrategyConfig config) throws IOException {
        this.config = config;
        this.simLatencyNanos = config.simLatencyMs * 1_000_000L;
        this.sizeHaircut = BigDecimal.valueOf(config.simSizeHaircut);
        Path dir = Path.of(config.ordersDir);
        Files.createDirectories(dir);
        String stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
        this.file = dir.resolve("sim-fills-" + stamp + ".jsonl");
        this.out = Files.newBufferedWriter(file, StandardCharsets.UTF_8);
        log.info("Sim fill writer opened: {} (latency={}ms, fee={}bps, haircut={})",
                file.toAbsolutePath(), config.simLatencyMs, config.simFeeBps, config.simSizeHaircut);

        this.snapshotFile = dir.resolve("position-snapshot.tsv");
        loadSnapshot();
        this.snapshotScheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "position-snapshot");
            t.setDaemon(true);
            return t;
        });
        snapshotScheduler.scheduleAtFixedRate(this::writeSnapshot, 30, 30, TimeUnit.SECONDS);
    }

    /** Seeds book replicas from a prior process's snapshot (same format SignalHandler writes,
     * already keyed venue|product) — call before any events are processed. */
    public void seedBooks(Map<String, TopBook> booksByVenueProduct) {
        books.putAll(booksByVenueProduct);
    }

    /** Restores position/PnL from a prior process's snapshot, if one exists. */
    private void loadSnapshot() {
        if (!Files.exists(snapshotFile)) {
            return;
        }
        int restored = 0;
        try {
            for (String line : Files.readAllLines(snapshotFile, StandardCharsets.UTF_8)) {
                if (line.isBlank()) {
                    continue;
                }
                String[] f = line.split("\t");
                if (f.length != 7) {
                    log.warn("Skipping malformed position snapshot line: {}", line);
                    continue;
                }
                trackers.computeIfAbsent(f[0], k -> new PositionTracker())
                        .restore(Double.parseDouble(f[1]), Double.parseDouble(f[2]),
                                Double.parseDouble(f[3]), Double.parseDouble(f[4]),
                                Long.parseLong(f[5]), Long.parseLong(f[6]));
                restored++;
            }
            log.info("Restored position snapshot from {} ({} product(s))", snapshotFile.toAbsolutePath(), restored);
        } catch (IOException | NumberFormatException ex) {
            log.error("Failed to load position snapshot from {} -- starting flat", snapshotFile.toAbsolutePath(), ex);
        }
    }

    /** Atomic write (temp file + rename) so a mid-write crash can't corrupt the snapshot a restart would read.
     * Catches Throwable, not just IOException: scheduleAtFixedRate silently and permanently stops future
     * runs of a task that ever propagates an uncaught exception (including an Error like OOM) -- this is a
     * best-effort periodic write, one bad iteration (e.g. a transient OOM under replay memory pressure)
     * must not disable every subsequent snapshot for the rest of the process's life. */
    private void writeSnapshot() {
        Path tmp = snapshotFile.resolveSibling(snapshotFile.getFileName() + ".tmp");
        try (BufferedWriter w = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
            for (Map.Entry<String, PositionTracker> e : trackers.entrySet()) {
                PositionTracker t = e.getValue();
                w.write(e.getKey() + "\t" + t.position() + "\t" + t.avgCost() + "\t"
                        + t.realizedPnl() + "\t" + t.feesPaid() + "\t" + t.fills() + "\t" + t.partialFills());
                w.newLine();
            }
            w.flush();
            Files.move(tmp, snapshotFile, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (Throwable ex) {
            log.error("Position snapshot write failed (will retry next interval)", ex);
        }
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        String product = event.delta.productId;
        String venue = event.delta.venue;
        if (product == null || venue == null) {
            return;
        }
        String key = venue + '|' + product;
        TopBook book = books.computeIfAbsent(key, k -> new TopBook());
        book.apply(event.delta);

        BigDecimal mid = book.mid();
        if (mid != null) {
            trackers.computeIfAbsent(key, k -> new PositionTracker()).markMid(mid.doubleValue());
        }

        if (event.riskApproved && event.delta.recvTsEpochNanos > 0) {
            long arrival = event.delta.recvTsEpochNanos + simLatencyNanos;
            if (event.arbSignal) {
                StrategyEvent.Leg buy = event.arbBuyLeg;
                StrategyEvent.Leg sell = event.arbSellLeg;
                pending.add(new SimOrder(buy.orderId, buy.venue, buy.productId,
                        StrategyEvent.SIGNAL_BUY, buy.qty, arrival));
                pending.add(new SimOrder(sell.orderId, sell.venue, sell.productId,
                        StrategyEvent.SIGNAL_SELL, sell.qty, arrival));
            } else if (event.signal != StrategyEvent.SIGNAL_NONE && event.orderQty != null) {
                pending.add(new SimOrder(event.orderId, venue, product, event.signal,
                        event.orderQty, arrival));
            }
        }

        // The md stream is the fill clock: any doc's recvTs advances "now";
        // a due order executes against its product's book as of that moment.
        long now = event.delta.recvTsEpochNanos;
        while (now > 0 && !pending.isEmpty() && pending.peek().arrivalTs <= now) {
            execute(pending.poll(), now);
        }
    }

    private void execute(SimOrder order, long execTs) {
        String key = order.venue + '|' + order.product;
        TopBook book = books.get(key);
        boolean buy = order.side == StrategyEvent.SIGNAL_BUY;
        TopBook.WalkResult r = book == null ? null : book.walk(buy, order.qty, sizeHaircut);
        if (r == null) {
            unfilledCount.incrementAndGet();
            log.warn("[{}] sim order {} UNFILLED (no liquidity on {} side)",
                    key, order.orderId, buy ? "ask" : "bid");
            return;
        }
        BigDecimal notional = r.avgPrice().multiply(r.filledQty());
        BigDecimal fee = notional.multiply(feeRates.computeIfAbsent(order.venue,
                v -> BigDecimal.valueOf(config.simFeeBps(v)).movePointLeft(4)));
        boolean partial = r.filledQty().compareTo(order.qty) < 0;

        PositionTracker tracker = trackers.computeIfAbsent(key, k -> new PositionTracker());
        double signedQty = buy ? r.filledQty().doubleValue() : -r.filledQty().doubleValue();
        tracker.onFill(signedQty, r.avgPrice().doubleValue(), fee.doubleValue(), partial);
        fillCount.incrementAndGet();
        writeFill(order, execTs, r, fee, partial, tracker);
    }

    private void writeFill(SimOrder order, long execTs, TopBook.WalkResult r,
                           BigDecimal fee, boolean partial, PositionTracker tracker) {
        try {
            out.write("{\"fillId\":" + (fillId++)
                    + ",\"orderId\":" + order.orderId
                    + ",\"tsEpochNanos\":" + execTs
                    + ",\"venue\":\"" + order.venue + '"'
                    + ",\"product\":\"" + order.product + '"'
                    + ",\"side\":\"" + (order.side == StrategyEvent.SIGNAL_BUY ? "BUY" : "SELL") + '"'
                    + ",\"requestedQty\":\"" + order.qty.toPlainString() + '"'
                    + ",\"filledQty\":\"" + r.filledQty().toPlainString() + '"'
                    + ",\"avgPrice\":\"" + r.avgPrice().toPlainString() + '"'
                    + ",\"fee\":\"" + fee.toPlainString() + '"'
                    + ",\"partial\":" + partial
                    + ",\"posAfter\":" + String.format("%.8f", tracker.position())
                    + ",\"realizedAfter\":" + String.format("%.6f", tracker.realizedPnl())
                    + "}");
            out.newLine();
            out.flush();
        } catch (IOException ex) {
            log.error("Sim fill write failed", ex);
        }
    }

    /** One line per product for the periodic [pnl] stats log. */
    public List<String> pnlSummaryLines() {
        List<String> lines = new ArrayList<>(trackers.size());
        for (Map.Entry<String, PositionTracker> e : trackers.entrySet()) {
            lines.add(e.getKey() + ": " + e.getValue().summary());
        }
        return lines;
    }

    public long fillCount() {
        return fillCount.get();
    }

    public long unfilledCount() {
        return unfilledCount.get();
    }

    @Override
    public void close() {
        snapshotScheduler.shutdownNow();
        writeSnapshot();
        try {
            out.close();
        } catch (IOException ignored) { }
        if (!pending.isEmpty()) {
            log.info("{} sim order(s) still pending at close (arrival beyond last doc) — dropped", pending.size());
        }
        log.info("Sim fill writer closed: {} fills ({} unfilled) in {}",
                fillCount.get(), unfilledCount.get(), file.toAbsolutePath());
        for (String line : pnlSummaryLines()) {
            log.info("[pnl-final] {}", line);
        }
    }

    private static final class SimOrder {
        final long orderId;
        final String venue;
        final String product;
        final int side;
        final BigDecimal qty;
        /** md-stream recvTs at which this order "reaches the exchange". */
        final long arrivalTs;

        SimOrder(long orderId, String venue, String product, int side, BigDecimal qty, long arrivalTs) {
            this.orderId = orderId;
            this.venue = venue;
            this.product = product;
            this.side = side;
            this.qty = qty;
            this.arrivalTs = arrivalTs;
        }
    }
}
