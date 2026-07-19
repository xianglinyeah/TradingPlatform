package com.yexl.trading.strategy.handlers;

import com.lmax.disruptor.EventHandler;
import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.marketdata.book.TopBook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Pipeline stage 1, arb mode — cross-venue basis mean-reversion.
 *
 * <p>Per logical symbol (e.g. BTC = COINBASE:BTC-USD vs OKX:BTC-USDT) the
 * handler tracks {@code spreadBps = (midB - midA) / midAvg * 1e4} and its
 * irregular-series EMA. The raw spread is NOT tradeable around zero: the
 * persistent USDT/USD basis parks it around a nonzero level for hours — so
 * the signal is deviation <b>from the EMA</b>, which also absorbs slow
 * stablecoin drift. dev &gt; +entry: B rich → sell B / buy A;
 * dev &lt; -entry: buy B / sell A. Both legs share one base qty (delta
 * neutral in base-currency terms), sized notional / mid.
 *
 * <p>Known-losing by construction at current fee tiers (entry bps ≪ round
 * trip fees) — this is a deliberate pipeline test, not an alpha claim.
 */
public final class ArbSignalHandler implements EventHandler<StrategyEvent> {

    private static final Logger log = LoggerFactory.getLogger(ArbSignalHandler.class);

    private final StrategyConfig config;
    private final boolean streamClock;

    /** Per venue|product book replica + freshness. */
    private static final class LegBook {
        final TopBook book = new TopBook();
        long lastRecvTsEpochNanos;
    }

    private static final class SymbolState {
        final String symbol;
        final String keyA;
        final String keyB;
        /** volatile: read by the stats thread for the [arb] diagnostics line. */
        volatile double emaBps;
        volatile double lastSpreadBps;
        volatile long samples;
        boolean emaInit;
        /** recvTs of the first spread sample — the EMA-age warmup gate anchor. */
        long firstSampleTs;
        /** recvTs of the previous spread sample (drives the irregular-series EMA alpha). */
        long lastSampleTs;
        /** 0 = never signaled. NOT Long.MIN_VALUE: nowNanos - MIN_VALUE
         * overflows negative and permanently trips the cooldown check. */
        long lastSignalNanos = 0L;

        SymbolState(String symbol, String keyA, String keyB) {
            this.symbol = symbol;
            this.keyA = keyA;
            this.keyB = keyB;
        }
    }

    private final Map<String, LegBook> books = new HashMap<>();
    /** venue|product -> symbols this leg participates in. */
    private final Map<String, List<SymbolState>> symbolsByLeg = new HashMap<>();
    /** All symbol states, for the periodic diagnostics line. */
    private final List<SymbolState> allSymbols = new ArrayList<>();

    private final AtomicLong signalsGenerated = new AtomicLong();

    public ArbSignalHandler(StrategyConfig config) {
        this.config = config;
        this.streamClock = "stream".equals(config.clockMode);
        for (Map.Entry<String, String[]> e : config.arbSymbols.entrySet()) {
            String[] legs = e.getValue(); // [venA, prodA, venB, prodB]
            String keyA = legs[0] + '|' + legs[1];
            String keyB = legs[2] + '|' + legs[3];
            SymbolState st = new SymbolState(e.getKey(), keyA, keyB);
            allSymbols.add(st);
            symbolsByLeg.computeIfAbsent(keyA, k -> new ArrayList<>()).add(st);
            symbolsByLeg.computeIfAbsent(keyB, k -> new ArrayList<>()).add(st);
            books.put(keyA, new LegBook());
            books.put(keyB, new LegBook());
            log.info("Arb symbol {}: {} vs {}", e.getKey(), keyA, keyB);
        }
    }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        String venue = event.delta.venue;
        String product = event.delta.productId;
        if (venue == null || product == null) {
            return;
        }
        String key = venue + '|' + product;
        LegBook lb = books.get(key);
        if (lb == null) {
            return; // product not part of any configured symbol
        }
        lb.book.apply(event.delta);
        if (event.delta.recvTsEpochNanos > 0) {
            lb.lastRecvTsEpochNanos = event.delta.recvTsEpochNanos;
        }

        // Replay/catchup guard (wall mode): books must be updated from
        // replayed history, but signaling on it would be trading on the past.
        if (!streamClock) {
            long docAgeMs = (event.consumeEpochNanos - event.delta.pubTsEpochNanos) / 1_000_000L;
            if (docAgeMs > config.signalMaxDocAgeMs) {
                return;
            }
        }

        List<SymbolState> symbols = symbolsByLeg.get(key);
        for (SymbolState st : symbols) {
            if (evaluate(st, event)) {
                return; // one arb signal per event
            }
        }
    }

    /** Returns true when a signal was emitted onto the event. */
    private boolean evaluate(SymbolState st, StrategyEvent event) {
        LegBook a = books.get(st.keyA);
        LegBook b = books.get(st.keyB);
        BigDecimal midA = a.book.mid();
        BigDecimal midB = b.book.mid();
        if (midA == null || midB == null) {
            return false;
        }
        long sampleTs = event.delta.recvTsEpochNanos;
        if (sampleTs <= 0) {
            return false;
        }

        double mA = midA.doubleValue();
        double mB = midB.doubleValue();
        double midAvg = (mA + mB) / 2.0;
        double spreadBps = (mB - mA) / midAvg * 1e4;
        st.lastSpreadBps = spreadBps;

        if (!st.emaInit) {
            st.emaBps = spreadBps;
            st.emaInit = true;
            st.samples = 1;
            st.firstSampleTs = sampleTs;
            st.lastSampleTs = sampleTs;
            return false;
        }
        // Irregular-series EMA: alpha from the actual inter-sample gap.
        double dtMs = Math.max(0, sampleTs - st.lastSampleTs) / 1_000_000.0;
        st.lastSampleTs = sampleTs;
        double alpha = 1.0 - Math.exp(-dtMs * Math.log(2) / config.arbEmaHalflifeMs);
        st.emaBps += alpha * (spreadBps - st.emaBps);
        st.samples++;
        if (st.samples < config.arbMinSamples) {
            return false;
        }
        // Age gate: sample count alone passes within seconds of catchup while
        // the EMA is still ~40bps from the true basis (observed live — the
        // first signals of the first run were pure warmup artifacts).
        if (sampleTs - st.firstSampleTs < config.arbEmaWarmupMs * 1_000_000L) {
            return false;
        }

        double devBps = spreadBps - st.emaBps;
        if (Math.abs(devBps) < config.arbEntryBps) {
            return false;
        }

        // Both legs must be concurrently fresh — a stale far leg means the
        // "spread" is partly a timestamp artifact, not a price.
        long maxAgeNanos = config.arbMaxLegAgeMs * 1_000_000L;
        if (sampleTs - a.lastRecvTsEpochNanos > maxAgeNanos
                || sampleTs - b.lastRecvTsEpochNanos > maxAgeNanos) {
            return false;
        }

        long nowNanos = streamClock ? sampleTs : System.currentTimeMillis() * 1_000_000L;
        if (nowNanos - st.lastSignalNanos < config.signalCooldownMs * 1_000_000L) {
            return false;
        }

        // dev > 0: B rich -> sell B, buy A. dev < 0: buy B, sell A.
        LegBook buyBook = devBps > 0 ? a : b;
        LegBook sellBook = devBps > 0 ? b : a;
        String buyKey = devBps > 0 ? st.keyA : st.keyB;
        String sellKey = devBps > 0 ? st.keyB : st.keyA;
        BigDecimal buyTouch = buyBook.book.bestAsk();
        BigDecimal sellTouch = sellBook.book.bestBid();
        if (buyTouch == null || sellTouch == null
                || buyTouch.signum() <= 0 || sellTouch.signum() <= 0) {
            return false;
        }
        BigDecimal qty = BigDecimal.valueOf(config.orderNotionalUsd(st.symbol))
                .divide(BigDecimal.valueOf(midAvg), 8, RoundingMode.DOWN);
        if (qty.signum() <= 0) {
            return false;
        }

        st.lastSignalNanos = nowNanos;
        fillLeg(event.arbBuyLeg, buyKey, qty, buyTouch);
        fillLeg(event.arbSellLeg, sellKey, qty, sellTouch);
        event.arbSignal = true;
        event.arbSymbol = st.symbol;
        event.arbDevBps = devBps;
        event.arbEmaBps = st.emaBps;
        event.signalNanos = System.nanoTime();
        signalsGenerated.incrementAndGet();

        if (log.isDebugEnabled()) {
            log.debug("[{}] arb signal: dev={}bps ema={}bps buy {} @{} sell {} @{} qty={}",
                    st.symbol, String.format("%.2f", devBps), String.format("%.2f", st.emaBps),
                    buyKey, buyTouch, sellKey, sellTouch, qty);
        }
        return true;
    }

    private static void fillLeg(StrategyEvent.Leg leg, String key, BigDecimal qty, BigDecimal touch) {
        int sep = key.indexOf('|');
        leg.venue = key.substring(0, sep);
        leg.productId = key.substring(sep + 1);
        leg.qty = qty;
        leg.touchPrice = touch.toPlainString();
    }

    public long signalsGeneratedCount() {
        return signalsGenerated.get();
    }

    /** One line per symbol for the periodic [arb] stats log. */
    public List<String> summaryLines() {
        List<String> lines = new ArrayList<>(allSymbols.size());
        for (SymbolState st : allSymbols) {
            double spread = st.lastSpreadBps;
            double ema = st.emaBps;
            lines.add(String.format("%s: spread=%.2fbps ema=%.2fbps dev=%.2fbps samples=%d",
                    st.symbol, spread, ema, spread - ema, st.samples));
        }
        return lines;
    }
}
