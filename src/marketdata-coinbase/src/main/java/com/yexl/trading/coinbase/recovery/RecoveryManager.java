package com.yexl.trading.coinbase.recovery;

import com.yexl.trading.coinbase.config.AppConfig;
import com.yexl.trading.coinbase.model.BookState;
import com.yexl.trading.coinbase.orderbook.OrderBook;
import com.yexl.trading.coinbase.orderbook.OrderBookManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Fault detection and recovery orchestrator for the market data pipeline.
 *
 * <p>Three trigger sources feed into this class, each from a different
 * thread, and each call is O(1)/non-blocking on the calling thread:
 * <ul>
 *   <li>{@link #onSequenceGap(long, long)} — called from {@code ParseHandler}
 *       (Disruptor Thread 2) when {@code sequence_num} skips forward.</li>
 *   <li>{@link #onChannelInactive()} — called from the Netty I/O thread when
 *       the WS channel drops or errors.</li>
 *   <li>The heartbeat watchdog (this class's own scheduled task) — fires when
 *       no heartbeat has been observed for
 *       {@code heartbeatExpectedIntervalMs * heartbeatMissedThreshold}.</li>
 * </ul>
 *
 * <p>All actual recovery work (marking books STALE, resubscribing, the
 * blocking reconnect-with-backoff loop) runs on a single dedicated
 * {@code recovery-manager} thread, never on the Netty I/O thread or a
 * Disruptor handler thread. Because that executor is single-threaded, all
 * recovery actions are naturally serialized — no separate locking is needed
 * to prevent concurrent reconnect/resubscribe attempts from racing.
 *
 * <p>Sequence gaps and heartbeat timeouts affect every configured product:
 * {@code sequence_num} is a connection-wide counter (a single WS frame's
 * {@code events[]} can carry updates for multiple products), so a gap can't
 * be attributed to one product — the only sound response is to distrust all
 * of them. Heartbeats aren't per-product at all.
 */
public final class RecoveryManager {

    private static final Logger log = LoggerFactory.getLogger(RecoveryManager.class);

    private final AppConfig config;
    private final OrderBookManager orderBookManager;
    private final ScheduledExecutorService executor;

    private volatile RecoverableConnection connection;

    /** True while a reconnect-with-backoff loop is in flight. Gates duplicate reconnect triggers. */
    private final AtomicBoolean reconnecting = new AtomicBoolean(false);
    private final AtomicBoolean shuttingDown = new AtomicBoolean(false);

    /** Updated on every HEARTBEAT event and on successful (re)connect. 0 = none observed yet. */
    private final AtomicLong lastHeartbeatNanos = new AtomicLong(0L);

    private final AtomicLong sequenceGapCount = new AtomicLong();
    private final AtomicLong disconnectCount = new AtomicLong();
    private final AtomicLong heartbeatTimeoutCount = new AtomicLong();
    private final AtomicLong staleTransitionCount = new AtomicLong();
    private final AtomicLong recoveredCount = new AtomicLong();
    private final AtomicLong reconnectAttemptCount = new AtomicLong();

    public RecoveryManager(AppConfig config, OrderBookManager orderBookManager) {
        this.config = config;
        this.orderBookManager = orderBookManager;
        this.executor = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "recovery-manager");
            t.setDaemon(true);
            return t;
        });
    }

    /** Wires the connection this manager drives. Must be called once before {@link #start()}. */
    public void attachConnection(RecoverableConnection connection) {
        this.connection = connection;
    }

    /** Starts the heartbeat-timeout watchdog. */
    public void start() {
        long thresholdMs = config.heartbeatExpectedIntervalMs * config.heartbeatMissedThreshold;
        executor.scheduleAtFixedRate(
                this::heartbeatWatchdogTick,
                thresholdMs,
                config.heartbeatExpectedIntervalMs,
                TimeUnit.MILLISECONDS
        );
        log.info("RecoveryManager started (heartbeat timeout threshold={}ms, reconnect backoff {}ms..{}ms)",
                thresholdMs, config.reconnectInitialBackoffMs, config.reconnectMaxBackoffMs);
    }

    public void shutdown() {
        shuttingDown.set(true);
        executor.shutdownNow();
        log.info("RecoveryManager stopped (sequenceGaps={}, disconnects={}, heartbeatTimeouts={}, " +
                "staleTransitions={}, recovered={}, reconnectAttempts={})",
                sequenceGapCount.get(), disconnectCount.get(), heartbeatTimeoutCount.get(),
                staleTransitionCount.get(), recoveredCount.get(), reconnectAttemptCount.get());
    }

    // ---- Trigger source #1: sequence gap (called from ParseHandler, Thread 2) ----

    /** Non-blocking: only increments a counter and enqueues work on the recovery thread. */
    public void onSequenceGap(long expectedNext, long actualSeq) {
        sequenceGapCount.incrementAndGet();
        executor.submit(() -> handleSequenceGap(expectedNext, actualSeq));
    }

    private void handleSequenceGap(long expectedNext, long actualSeq) {
        if (shuttingDown.get()) {
            return;
        }
        log.warn("Sequence gap detected: expected={} actual={} (missed {} message(s)) — " +
                "marking all products STALE", expectedNext, actualSeq, actualSeq - expectedNext);
        markAllStale("sequence-gap");
        if (reconnecting.get()) {
            log.debug("Reconnect already in flight; skipping standalone resubscribe " +
                    "(reconnect will resubscribe all products)");
            return;
        }
        RecoverableConnection conn = connection;
        if (conn != null) {
            conn.resubscribeLevel2(config.productIds);
        }
    }

    // ---- Trigger source #2: disconnect (called from Netty I/O thread) ----

    /** Non-blocking: only increments a counter and (maybe) CASes + submits the reconnect loop. */
    public void onChannelInactive() {
        disconnectCount.incrementAndGet();
        triggerReconnectRecovery("disconnect");
    }

    // ---- Called from Netty I/O thread once a new WS handshake completes ----

    public void onChannelActive() {
        lastHeartbeatNanos.set(System.nanoTime());
        log.info("Connection (re)established; heartbeat watchdog baseline reset");
    }

    // ---- Trigger source #3: heartbeat timeout (this class's own watchdog thread) ----

    private void heartbeatWatchdogTick() {
        if (reconnecting.get()) {
            return;
        }
        long last = lastHeartbeatNanos.get();
        if (last == 0L) {
            return; // startup grace period: no heartbeat observed yet
        }
        long thresholdNanos = config.heartbeatExpectedIntervalMs * config.heartbeatMissedThreshold * 1_000_000L;
        long elapsedNanos = System.nanoTime() - last;
        if (elapsedNanos > thresholdNanos) {
            heartbeatTimeoutCount.incrementAndGet();
            log.error("Heartbeat timeout: no heartbeat for {}ms (threshold {}ms)",
                    elapsedNanos / 1_000_000L, thresholdNanos / 1_000_000L);
            triggerReconnectRecovery("heartbeat-timeout");
        }
    }

    // ---- Called from OrderBookHandler (Thread 3) on every HEARTBEAT event ----

    /** Non-blocking: a single volatile write. */
    public void onHeartbeat() {
        lastHeartbeatNanos.set(System.nanoTime());
    }

    // ---- Called from OrderBookHandler (Thread 3) right after a snapshot revives a STALE book ----

    /** Non-blocking: a counter increment + log line. */
    public void onRecovered(String productId) {
        recoveredCount.incrementAndGet();
        log.info("[{}] Recovered: STALE -> LIVE", productId);
    }

    // ---- Shared reconnect path for disconnect and heartbeat-timeout ----

    private void triggerReconnectRecovery(String reason) {
        if (shuttingDown.get()) {
            log.debug("Shutting down; ignoring {} trigger", reason);
            return;
        }
        if (!reconnecting.compareAndSet(false, true)) {
            log.debug("Reconnect already in flight; ignoring {} trigger", reason);
            return;
        }
        executor.submit(() -> {
            try {
                log.warn("Recovery triggered by {}: marking all products STALE and reconnecting", reason);
                markAllStale(reason);
                reconnectLoop();
            } catch (Exception e) {
                log.error("Unexpected error during {} recovery", reason, e);
            } finally {
                reconnecting.set(false);
            }
        });
    }

    private void reconnectLoop() {
        RecoverableConnection conn = connection;
        if (conn == null) {
            log.error("No connection attached; cannot reconnect");
            return;
        }
        long delayMs = config.reconnectInitialBackoffMs;
        int attempt = 0;
        while (!shuttingDown.get()) {
            attempt++;
            reconnectAttemptCount.incrementAndGet();
            try {
                log.info("Reconnect attempt #{}", attempt);
                conn.reconnect();
                // conn.reconnect() returning only means the local TCP hop (to
                // the proxy, if any) connected — the real WS handshake with
                // Coinbase still completes asynchronously afterward and can
                // take longer than one heartbeat-timeout window, especially
                // tunneled through a proxy. Push the staleness clock forward
                // now so the watchdog doesn't immediately judge this brand
                // new, still-handshaking connection dead and tear it down
                // before it gets a chance to finish. onChannelActive() will
                // push it forward again for real once the handshake actually
                // completes.
                lastHeartbeatNanos.set(System.nanoTime());
                log.info("Reconnect attempt #{} succeeded", attempt);
                return;
            } catch (Exception e) {
                log.error("Reconnect attempt #{} failed, retrying in {}ms", attempt, delayMs, e);
                sleepUninterruptibly(delayMs);
                delayMs = Math.min(delayMs * 2, config.reconnectMaxBackoffMs);
            }
        }
    }

    private void sleepUninterruptibly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void markAllStale(String reason) {
        for (String productId : config.productIds) {
            OrderBook book = orderBookManager.getOrCreate(productId);
            BookState before = book.state();
            book.clearForResubscribe();
            if (before != BookState.STALE) {
                staleTransitionCount.incrementAndGet();
                log.warn("[{}] state {} -> STALE (reason={})", productId, before, reason);
            }
        }
    }

    // ---- Counters for BookMonitor ----

    public long sequenceGapCount() {
        return sequenceGapCount.get();
    }

    public long disconnectCount() {
        return disconnectCount.get();
    }

    public long heartbeatTimeoutCount() {
        return heartbeatTimeoutCount.get();
    }

    public long staleTransitionCount() {
        return staleTransitionCount.get();
    }

    public long recoveredCount() {
        return recoveredCount.get();
    }

    public long reconnectAttemptCount() {
        return reconnectAttemptCount.get();
    }
}
