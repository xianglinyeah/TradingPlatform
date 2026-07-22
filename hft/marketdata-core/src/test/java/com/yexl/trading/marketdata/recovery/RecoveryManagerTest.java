package com.yexl.trading.marketdata.recovery;

import com.yexl.trading.marketdata.book.OrderBook;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.model.BookState;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.Side;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RecoveryManagerTest {

    private RecoveryManager manager;

    private static final class FakeConnection implements RecoverableConnection {
        final AtomicInteger reconnectCalls = new AtomicInteger();
        final List<List<String>> resubscribeCalls = new CopyOnWriteArrayList<>();

        @Override
        public void reconnect() {
            reconnectCalls.incrementAndGet();
        }

        @Override
        public void resubscribeLevel2(List<String> productIds) {
            resubscribeCalls.add(List.copyOf(productIds));
        }
    }

    private static RecoverySettings settings(String... productIds) {
        return new RecoverySettings(1000L, 3, 10L, 20L, List.of(productIds));
    }

    private static RecoverySettings settingsWithResnapshot(long resnapshotIntervalMs, String... productIds) {
        return new RecoverySettings(1000L, 3, 10L, 20L, List.of(productIds), resnapshotIntervalMs);
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

    @AfterEach
    void tearDown() {
        if (manager != null) {
            manager.shutdown();
        }
    }

    @Test
    void sequenceGapMarksAllConfiguredProductsStaleAndResubscribes() {
        OrderBookManager books = new OrderBookManager();
        RecoverySettings s = settings("BTC-USD", "ETH-USD");
        manager = new RecoveryManager(s, books);
        FakeConnection conn = new FakeConnection();
        manager.attachConnection(conn);

        // Give both books a LIVE snapshot first so the STALE transition is observable.
        BookUpdate bid = new BookUpdate();
        bid.set(Side.BID, "x", new BigDecimal("1"), new BigDecimal("1"), 0L, false);
        books.getOrCreate("BTC-USD").applySnapshot(List.of(bid));
        books.getOrCreate("ETH-USD").applySnapshot(List.of(bid));

        manager.onSequenceGap(10L, 15L);

        awaitTrue(() -> !conn.resubscribeCalls.isEmpty(), 2000);
        assertEquals(BookState.STALE, books.get("BTC-USD").state());
        assertEquals(BookState.STALE, books.get("ETH-USD").state());
        assertEquals(1, conn.resubscribeCalls.size());
        assertEquals(List.of("BTC-USD", "ETH-USD"), conn.resubscribeCalls.get(0));
        assertEquals(1, manager.sequenceGapCount());
    }

    @Test
    void disconnectTriggersReconnectLoopWhichSucceedsOnFirstAttempt() {
        OrderBookManager books = new OrderBookManager();
        manager = new RecoveryManager(settings("BTC-USD"), books);
        FakeConnection conn = new FakeConnection();
        manager.attachConnection(conn);

        manager.onChannelInactive();

        awaitTrue(() -> conn.reconnectCalls.get() >= 1, 2000);
        assertEquals(1, manager.disconnectCount());
        awaitTrue(() -> manager.reconnectAttemptCount() >= 1, 2000);
    }

    @Test
    void bookCorruptionThrottlesRepeatedReportsWithinWindow() {
        OrderBookManager books = new OrderBookManager();
        manager = new RecoveryManager(settings("BTC-USD"), books);
        FakeConnection conn = new FakeConnection();
        manager.attachConnection(conn);

        manager.onBookCorruption("checksum");
        manager.onBookCorruption("checksum"); // same throttle window (5s) -> dropped

        awaitTrue(() -> !conn.resubscribeCalls.isEmpty(), 2000);
        // Give the second (dropped) submission a moment to have run too, then
        // confirm it didn't add a second resubscribe.
        try {
            Thread.sleep(100);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        assertEquals(1, conn.resubscribeCalls.size());
    }

    @Test
    void periodicResnapshotFiresOnItsOwnWithNoErrorTrigger() {
        OrderBookManager books = new OrderBookManager();
        RecoverySettings s = settingsWithResnapshot(30L, "BTC-USD");
        manager = new RecoveryManager(s, books);
        FakeConnection conn = new FakeConnection();
        manager.attachConnection(conn);

        BookUpdate bid = new BookUpdate();
        bid.set(Side.BID, "x", new BigDecimal("1"), new BigDecimal("1"), 0L, false);
        books.getOrCreate("BTC-USD").applySnapshot(List.of(bid));

        manager.start();

        awaitTrue(() -> !conn.resubscribeCalls.isEmpty(), 2000);
        assertEquals(BookState.STALE, books.get("BTC-USD").state());
        assertEquals(List.of("BTC-USD"), conn.resubscribeCalls.get(0));
    }

    @Test
    void zeroResnapshotIntervalNeverFires() throws InterruptedException {
        OrderBookManager books = new OrderBookManager();
        manager = new RecoveryManager(settings("BTC-USD"), books); // 5-arg ctor -> resnapshot disabled
        FakeConnection conn = new FakeConnection();
        manager.attachConnection(conn);

        manager.start();
        Thread.sleep(200);

        assertTrue(conn.resubscribeCalls.isEmpty());
    }

    @Test
    void onHeartbeatAndOnRecoveredUpdateCountersWithoutThrowing() {
        OrderBookManager books = new OrderBookManager();
        manager = new RecoveryManager(settings("BTC-USD"), books);
        manager.attachConnection(new FakeConnection());

        manager.onHeartbeat();
        manager.onRecovered("BTC-USD");

        assertEquals(1, manager.recoveredCount());
    }
}
