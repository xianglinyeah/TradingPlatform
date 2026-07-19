package com.yexl.trading.strategy.handlers;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.marketdata.book.TopBook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
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

    private final StrategyConfig config;
    private final Map<String, TopBook> books = new HashMap<>();
    private final Map<String, Long> lastSignalMs = new HashMap<>();

    private final AtomicLong signalsGenerated = new AtomicLong();

    public SignalHandler(StrategyConfig config) {
        this.config = config;
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        String product = event.delta.productId;
        if (product == null) {
            return;
        }
        TopBook book = books.computeIfAbsent(product, k -> new TopBook());
        book.apply(event.delta);

        if (!book.ready(config.imbalanceLevels)) {
            return;
        }

        // Replay/catchup guard: during tail-from=start the pipeline chews
        // through hours of retained history — the book must be updated from
        // it, but signaling on it would be trading on the past. First live
        // E2E run generated an order from a 3.5h-old replayed doc.
        long docAgeMs = (event.consumeEpochNanos - event.delta.pubTsEpochNanos) / 1_000_000L;
        if (docAgeMs > config.signalMaxDocAgeMs) {
            return;
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

        long nowMs = System.currentTimeMillis();
        Long last = lastSignalMs.get(product);
        if (last != null && nowMs - last < config.signalCooldownMs) {
            return;
        }
        lastSignalMs.put(product, nowMs);

        BigDecimal touch = (sig == StrategyEvent.SIGNAL_BUY) ? book.bestAsk() : book.bestBid();
        event.signal = sig;
        event.touchPrice = touch != null ? touch.toPlainString() : null;
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
}
