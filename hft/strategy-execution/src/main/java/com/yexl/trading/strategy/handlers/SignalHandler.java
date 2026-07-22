package com.yexl.trading.strategy.handlers;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.marketdata.book.TopBook;
import com.yexl.trading.strategy.md.BookSnapshotIO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Pipeline stage 1 — maintains per-product book replicas from the delta
 * stream and emits the simplest honest imbalance signal.
 *
 * <p>Signal: ratio = sum(top-N bid qty) / sum(top-N ask qty).
 * ratio ≥ T → BUY; ratio ≤ 1/T → SELL. Per-product cooldown suppresses
 * signal spam. Deliberately naive — this validates the pipeline, not the
 * strategy.
 */
public final class SignalHandler implements EventHandler<StrategyEvent> {

    private static final Logger log = LoggerFactory.getLogger(SignalHandler.class);

    /** 30s: same cadence as the position snapshot; independent of it since the two
     * live on different Disruptor handler threads and must not share state. */
    private static final long SNAPSHOT_INTERVAL_NANOS = 30_000_000_000L;
    private static final int SNAPSHOT_MAX_LEVELS_PER_SIDE = 100;

    private final StrategyConfig config;
    /** stream mode: "now" is the current doc's recvTs — see StrategyConfig.clockMode. */
    private final boolean streamClock;
    private final Map<String, TopBook> books = new HashMap<>();
    private final Map<String, Long> lastSignalNanos = new HashMap<>();

    private final AtomicLong signalsGenerated = new AtomicLong();

    /** Null (feature off) unless single-queue imbalance mode wires one in — see Main. */
    private final Path bookSnapshotFile;
    private long lastSnapshotWriteNanos;

    public SignalHandler(StrategyConfig config) {
        this(config, null);
    }

    /**
     * @param bookSnapshotFile if non-null, this handler periodically checkpoints its book
     *                         replicas + the triggering event's queue index here (see
     *                         BookSnapshotIO), so a restart can resume without a full replay.
     *                         Seeding from a prior snapshot is the caller's job (Main), before
     *                         any events flow — see {@link #seedBooks}.
     */
    public SignalHandler(StrategyConfig config, Path bookSnapshotFile) {
        this.config = config;
        this.streamClock = "stream".equals(config.clockMode);
        this.bookSnapshotFile = bookSnapshotFile;
    }

    /** Seeds book replicas from a prior process's snapshot — call before any events are
     * processed. Keys are "venue|product"; this handler's own map is product-only
     * (imbalance mode assumes a single venue), so the venue prefix is stripped here. */
    public void seedBooks(Map<String, TopBook> booksByVenueProduct) {
        for (Map.Entry<String, TopBook> e : booksByVenueProduct.entrySet()) {
            String key = e.getKey();
            int sep = key.indexOf('|');
            String product = sep >= 0 ? key.substring(sep + 1) : key;
            books.put(product, e.getValue());
        }
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        String product = event.delta.productId;
        if (product == null) {
            return;
        }
        TopBook book = books.computeIfAbsent(product, k -> new TopBook());
        book.apply(event.delta);
        maybeWriteSnapshot(event);

        if (!book.ready(config.imbalanceLevels)) {
            return;
        }

        // Replay/catchup guard: during tail-from=start the pipeline chews
        // through hours of retained history — the book must be updated from
        // it, but signaling on it would be trading on the past. First live
        // E2E run generated an order from a 3.5h-old replayed doc.
        // Backtest (stream clock) inverts this: replayed history is exactly
        // what we trade on, so the gate is wall-mode only.
        if (!streamClock) {
            long docAgeMs = (event.consumeEpochNanos - event.delta.pubTsEpochNanos) / 1_000_000L;
            if (docAgeMs > config.signalMaxDocAgeMs) {
                return;
            }
        }

        double bidQty = book.topNBidQty(config.imbalanceLevels);
        double askQty = book.topNAskQty(config.imbalanceLevels);
        if (askQty <= 0 || bidQty <= 0) {
            return;
        }
        double ratio = bidQty / askQty;
        event.imbalance = ratio;

        int sig = StrategyEvent.SIGNAL_NONE;
        if (ratio >= config.imbalanceThreshold) {
            sig = StrategyEvent.SIGNAL_BUY;
        } else if (ratio <= 1.0 / config.imbalanceThreshold) {
            sig = StrategyEvent.SIGNAL_SELL;
        }
        if (sig == StrategyEvent.SIGNAL_NONE) {
            return;
        }

        long nowNanos = streamClock
                ? event.delta.recvTsEpochNanos
                : System.currentTimeMillis() * 1_000_000L;
        if (streamClock && nowNanos == 0) {
            return; // timestampless doc: can't place it on the stream timeline
        }
        Long last = lastSignalNanos.get(product);
        if (last != null && nowNanos - last < config.signalCooldownMs * 1_000_000L) {
            return;
        }
        lastSignalNanos.put(product, nowNanos);

        BigDecimal touch = (sig == StrategyEvent.SIGNAL_BUY) ? book.bestAsk() : book.bestBid();
        if (touch == null || touch.signum() <= 0) {
            return; // can't size a notional-based order without a price
        }
        BigDecimal qty = BigDecimal.valueOf(config.orderNotionalUsd(product))
                .divide(touch, 8, RoundingMode.DOWN);
        if (qty.signum() <= 0) {
            return;
        }
        event.signal = sig;
        event.touchPrice = touch.toPlainString();
        event.orderQty = qty;
        event.signalNanos = System.nanoTime();
        signalsGenerated.incrementAndGet();

        if (log.isDebugEnabled()) {
            log.debug("[{}] signal={} imbalance={} touch={}",
                    product, sig == 1 ? "BUY" : "SELL", ratio, event.touchPrice);
        }
    }

    public long signalsGeneratedCount() {
        return signalsGenerated.get();
    }

    /** Best-effort periodic checkpoint of book state + queue position, gated to
     * ~{@link #SNAPSHOT_INTERVAL_NANOS}. Runs entirely on this handler's own thread —
     * no locking, no cross-thread visibility concerns, unlike a separate scheduler
     * thread would need for a plain (non-concurrent) {@code books} map. */
    private void maybeWriteSnapshot(StrategyEvent event) {
        if (bookSnapshotFile == null || event.queueIndex < 0) {
            return;
        }
        long now = System.nanoTime();
        if (lastSnapshotWriteNanos != 0 && now - lastSnapshotWriteNanos < SNAPSHOT_INTERVAL_NANOS) {
            return;
        }
        lastSnapshotWriteNanos = now;
        String venue = event.delta.venue;
        Map<String, TopBook> byVenueProduct = new HashMap<>();
        for (Map.Entry<String, TopBook> e : books.entrySet()) {
            byVenueProduct.put(venue + "|" + e.getKey(), e.getValue());
        }
        BookSnapshotIO.write(bookSnapshotFile, event.queueIndex, byVenueProduct, SNAPSHOT_MAX_LEVELS_PER_SIDE);
    }
}
