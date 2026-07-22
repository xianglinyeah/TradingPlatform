package com.yexl.trading.okx.disruptor;

import com.yexl.trading.marketdata.book.OrderBook;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.model.BookState;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.model.OrderBookSnapshot;
import com.yexl.trading.marketdata.model.PriceLevel;
import com.yexl.trading.marketdata.model.Side;
import com.yexl.trading.marketdata.recovery.RecoverableConnection;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import com.yexl.trading.marketdata.recovery.RecoverySettings;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.BooleanSupplier;
import java.util.zip.CRC32;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OkxChecksumValidatorTest {

    private static final String INST_ID = "BTC-USDT";

    private RecoveryManager recoveryManager;

    private static final class FakeConnection implements RecoverableConnection {
        final List<List<String>> resubscribeCalls = new CopyOnWriteArrayList<>();

        @Override
        public void reconnect() { }

        @Override
        public void resubscribeLevel2(List<String> productIds) {
            resubscribeCalls.add(List.copyOf(productIds));
        }
    }

    @AfterEach
    void tearDown() {
        if (recoveryManager != null) {
            recoveryManager.shutdown();
        }
    }

    private static void awaitTrue(BooleanSupplier condition, long timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            if (condition.getAsBoolean()) {
                return;
            }
            try {
                Thread.sleep(10);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new RuntimeException(e);
            }
        }
        assertTrue(condition.getAsBoolean(), "condition not met within " + timeoutMs + "ms");
    }

    /** Mirrors OkxChecksumValidator's own interleave-and-CRC32 algorithm, for computing the expected value. */
    private static int expectedChecksum(OrderBookSnapshot snap) {
        List<PriceLevel> bids = snap.bids();
        List<PriceLevel> asks = snap.asks();
        StringBuilder sb = new StringBuilder();
        int n = Math.max(bids.size(), asks.size());
        for (int i = 0; i < n; i++) {
            if (i < bids.size()) {
                append(sb, bids.get(i));
            }
            if (i < asks.size()) {
                append(sb, asks.get(i));
            }
        }
        CRC32 crc = new CRC32();
        crc.update(sb.toString().getBytes(StandardCharsets.UTF_8));
        return (int) crc.getValue();
    }

    private static void append(StringBuilder sb, PriceLevel lvl) {
        if (sb.length() > 0) {
            sb.append(':');
        }
        sb.append(lvl.price().toPlainString()).append(':').append(lvl.qty().toPlainString());
    }

    private static OrderBookManager bookWithLevels() {
        OrderBookManager manager = new OrderBookManager();
        OrderBook book = manager.getOrCreate(INST_ID);
        BookUpdate b1 = new BookUpdate();
        b1.set(Side.BID, INST_ID, new BigDecimal("100"), new BigDecimal("1"), 0L, false);
        BookUpdate b2 = new BookUpdate();
        b2.set(Side.BID, INST_ID, new BigDecimal("99"), new BigDecimal("2"), 0L, false);
        BookUpdate a1 = new BookUpdate();
        a1.set(Side.ASK, INST_ID, new BigDecimal("101"), new BigDecimal("1"), 0L, false);
        book.applySnapshot(List.of(b1, b2, a1));
        return manager;
    }

    private static MarketDataEvent eventWithChecksum(int checksum) {
        MarketDataEvent event = new MarketDataEvent();
        event.bookChecksumPresent = true;
        event.updateCount = 1;
        BookUpdate u = new BookUpdate();
        u.productId = INST_ID;
        event.updates = new BookUpdate[]{u};
        event.bookChecksum = checksum;
        return event;
    }

    @Test
    void matchingChecksumLeavesBookLiveAndDoesNotTriggerRecovery() {
        OrderBookManager manager = bookWithLevels();
        FakeConnection conn = new FakeConnection();
        recoveryManager = new RecoveryManager(new RecoverySettings(1000L, 3, 10L, 20L, List.of(INST_ID)), manager);
        recoveryManager.attachConnection(conn);
        OkxChecksumValidator validator = new OkxChecksumValidator(recoveryManager);

        int correct = expectedChecksum(manager.get(INST_ID).snapshot(25));
        validator.afterApply(eventWithChecksum(correct), manager);

        assertEquals(BookState.LIVE, manager.get(INST_ID).state());
        assertTrue(conn.resubscribeCalls.isEmpty());
    }

    @Test
    void mismatchedChecksumMarksBookStaleAndTriggersResubscribe() {
        OrderBookManager manager = bookWithLevels();
        FakeConnection conn = new FakeConnection();
        recoveryManager = new RecoveryManager(new RecoverySettings(1000L, 3, 10L, 20L, List.of(INST_ID)), manager);
        recoveryManager.attachConnection(conn);
        OkxChecksumValidator validator = new OkxChecksumValidator(recoveryManager);

        int correct = expectedChecksum(manager.get(INST_ID).snapshot(25));
        validator.afterApply(eventWithChecksum(correct + 1), manager);

        awaitTrue(() -> manager.get(INST_ID).state() == BookState.STALE, 2000);
        awaitTrue(() -> !conn.resubscribeCalls.isEmpty(), 2000);
    }

    @Test
    void framesWithoutChecksumOrEmptyUpdatesAreIgnored() {
        OrderBookManager manager = bookWithLevels();
        FakeConnection conn = new FakeConnection();
        recoveryManager = new RecoveryManager(new RecoverySettings(1000L, 3, 10L, 20L, List.of(INST_ID)), manager);
        recoveryManager.attachConnection(conn);
        OkxChecksumValidator validator = new OkxChecksumValidator(recoveryManager);

        MarketDataEvent noChecksum = eventWithChecksum(0);
        noChecksum.bookChecksumPresent = false;
        validator.afterApply(noChecksum, manager);

        MarketDataEvent zeroUpdates = eventWithChecksum(0);
        zeroUpdates.updateCount = 0;
        validator.afterApply(zeroUpdates, manager);

        assertEquals(BookState.LIVE, manager.get(INST_ID).state());
        assertTrue(conn.resubscribeCalls.isEmpty());
    }
}
