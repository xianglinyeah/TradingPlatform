package com.yexl.trading.strategy.handlers;

import com.yexl.trading.strategy.StrategyConfig;
import com.yexl.trading.strategy.StrategyEvent;
import com.yexl.trading.marketdata.wire.MdDelta;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ArbSignalHandlerTest {

    private final List<String> propertiesToClear = new ArrayList<>();

    @AfterEach
    void tearDown() {
        for (String key : propertiesToClear) {
            System.clearProperty(key);
        }
        propertiesToClear.clear();
    }

    private void override(String key, String value) {
        System.setProperty(key, value);
        propertiesToClear.add(key);
    }

    private StrategyConfig arbConfig() {
        override("clock.mode", "stream");
        override("strategy.mode", "arb");
        override("arb.symbol.BTC", "COINBASE:BTC-USD,OKX:BTC-USDT");
        override("arb.min-samples", "3");
        override("arb.ema-warmup-ms", "1");
        override("arb.max-leg-age-ms", "10000");
        override("arb.entry-bps", "3.0");
        override("arb.ema-halflife-ms", "60000");
        override("signal.cooldown-ms", "1000");
        override("order.notional-usd", "100");
        return StrategyConfig.load();
    }

    private static StrategyEvent legEvent(String venue, String product, long recvTs,
                                          String bidPrice, String bidQty, String askPrice, String askQty) {
        StrategyEvent event = new StrategyEvent();
        MdDelta d = event.delta;
        d.venue = venue;
        d.productId = product;
        d.snapshot = true;
        d.recvTsEpochNanos = recvTs;
        d.pubTsEpochNanos = recvTs;
        d.prepareLevels(2);
        d.setLevel(0, MdDelta.SIDE_BID, bidPrice, bidQty);
        d.setLevel(1, MdDelta.SIDE_ASK, askPrice, askQty);
        return event;
    }

    @Test
    void noSignalUntilBothLegsHaveAMidPrice() {
        ArbSignalHandler handler = new ArbSignalHandler(arbConfig());

        StrategyEvent legAOnly = legEvent("COINBASE", "BTC-USD", 1_000_000_000L, "100", "1", "100.1", "1");
        handler.onEvent(legAOnly, 0, true);

        assertFalse(legAOnly.arbSignal);
        assertEquals(0, handler.signalsGeneratedCount());
    }

    @Test
    void unconfiguredProductIsIgnoredWithoutError() {
        ArbSignalHandler handler = new ArbSignalHandler(arbConfig());

        StrategyEvent unrelated = legEvent("COINBASE", "ETH-USD", 1_000_000_000L, "10", "1", "10.1", "1");
        handler.onEvent(unrelated, 0, true);

        assertFalse(unrelated.arbSignal);
    }

    @Test
    void noSignalWhileSpreadTracksItsOwnEma() {
        ArbSignalHandler handler = arbSignalHandlerWithStableSpreadWarmedUp();
        // handled inside the warmup helper: all warmup events assert no signal
        assertEquals(0, handler.signalsGeneratedCount());
    }

    @Test
    void largeSpreadJumpAfterWarmupEmitsTwoLegArbSignal() {
        ArbSignalHandler handler = arbSignalHandlerWithStableSpreadWarmedUp();

        // Leg B mid jumps from ~100.10 to ~100.50 — spread deviates far past
        // the 3bps entry threshold while the near-static EMA barely moves.
        StrategyEvent jump = legEvent("OKX", "BTC-USDT", 1_004_000_000L, "100.45", "1", "100.55", "1");
        handler.onEvent(jump, 0, true);

        assertTrue(jump.arbSignal);
        assertEquals("BTC", jump.arbSymbol);
        assertTrue(jump.arbDevBps > 3.0, "expected deviation well past the entry threshold, got " + jump.arbDevBps);

        // dev > 0 (B rich) => sell B / buy A
        assertEquals("COINBASE", jump.arbBuyLeg.venue);
        assertEquals("BTC-USD", jump.arbBuyLeg.productId);
        assertEquals("100.1", jump.arbBuyLeg.touchPrice); // leg A's ask, unchanged since seeding
        assertEquals("OKX", jump.arbSellLeg.venue);
        assertEquals("BTC-USDT", jump.arbSellLeg.productId);
        assertEquals("100.45", jump.arbSellLeg.touchPrice); // leg B's bid at signal time
        assertTrue(jump.arbBuyLeg.qty.signum() > 0);
        assertEquals(0, jump.arbBuyLeg.qty.compareTo(jump.arbSellLeg.qty)); // delta-neutral: same base qty both legs

        assertEquals(1, handler.signalsGeneratedCount());
    }

    /**
     * Seeds leg A once, then feeds leg B three samples at a constant spread —
     * enough to satisfy arb.min-samples=3 and the (tiny) warmup age gate
     * without ever deviating from the EMA it seeds. Asserts no signal fires
     * during warmup, matching what a stable, already-converged cross-venue
     * spread looks like before a real dislocation.
     */
    private ArbSignalHandler arbSignalHandlerWithStableSpreadWarmedUp() {
        ArbSignalHandler handler = new ArbSignalHandler(arbConfig());

        StrategyEvent seedA = legEvent("COINBASE", "BTC-USD", 1_000_000_000L, "100", "1", "100.1", "1");
        handler.onEvent(seedA, 0, true);
        assertFalse(seedA.arbSignal);

        for (long ts : new long[]{1_001_000_000L, 1_002_000_000L, 1_003_000_000L}) {
            StrategyEvent e = legEvent("OKX", "BTC-USDT", ts, "100.05", "1", "100.15", "1");
            handler.onEvent(e, 0, true);
            assertFalse(e.arbSignal, "unexpected signal at ts=" + ts);
        }
        return handler;
    }
}
