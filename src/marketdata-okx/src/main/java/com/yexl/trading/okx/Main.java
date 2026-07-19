package com.yexl.trading.okx;

import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.metrics.LatencyTracker;
import com.yexl.trading.marketdata.monitor.BookMonitor;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import com.yexl.trading.marketdata.recovery.RecoverySettings;
import com.yexl.trading.okx.config.AppConfig;
import com.yexl.trading.okx.disruptor.DisruptorOrchestrator;
import com.yexl.trading.okx.ws.OkxWsClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Entry point for the OKX market data process (Process A, OKX venue).
 * Same wiring as the Coinbase entry point, minus credentials — the public
 * books channel is unauthenticated.
 */
public final class Main {

    private static final Logger log = LoggerFactory.getLogger(Main.class);

    public static void main(String[] args) {
        // A trading process should not phone home. Set before any Chronicle
        // class loads.
        System.setProperty("chronicle.analytics.disable", "true");
        try {
            AppConfig config = AppConfig.load();

            OrderBookManager bookManager = new OrderBookManager();

            RecoveryManager recoveryManager = new RecoveryManager(new RecoverySettings(
                    config.heartbeatExpectedIntervalMs, config.heartbeatMissedThreshold,
                    config.reconnectInitialBackoffMs, config.reconnectMaxBackoffMs,
                    config.productIds), bookManager);

            LatencyTracker latencyTracker = new LatencyTracker();

            DisruptorOrchestrator disruptor = new DisruptorOrchestrator(
                    config, bookManager, recoveryManager, latencyTracker);
            disruptor.start();

            BookMonitor monitor = new BookMonitor(
                    bookManager, config.productIds, config.snapshotLogDepth, config.snapshotLogIntervalMs,
                    recoveryManager, latencyTracker, config.latencyLogIntervalMs);

            OkxWsClient wsClient = new OkxWsClient(
                    config, disruptor.disruptor().getRingBuffer(), recoveryManager);
            recoveryManager.attachConnection(wsClient);

            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                log.info("Shutdown hook triggered");
                try {
                    monitor.close();
                } catch (Exception ignored) { }
                // Stop the recovery manager before the WS client so the close it
                // triggers below doesn't get misread as a fault to recover from.
                try {
                    recoveryManager.shutdown();
                } catch (Exception ignored) { }
                try {
                    wsClient.stop();
                } catch (Exception ignored) { }
                try {
                    disruptor.shutdown();
                } catch (Exception ignored) { }
            }, "shutdown-hook"));

            monitor.start();
            wsClient.start();
            recoveryManager.start();
            log.info("Service started. Products={}. Press Ctrl-C to shut down.", config.productIds);

            wsClient.awaitClose();
            log.info("WS channel closed; main thread exiting");
        } catch (Exception e) {
            log.error("Fatal startup error", e);
            System.exit(1);
        }
    }
}
