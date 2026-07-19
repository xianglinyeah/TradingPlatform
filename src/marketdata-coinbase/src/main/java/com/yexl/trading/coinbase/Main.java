package com.yexl.trading.coinbase;

import com.yexl.trading.coinbase.auth.CdpCredentials;
import com.yexl.trading.coinbase.auth.JwtSigner;
import com.yexl.trading.coinbase.config.AppConfig;
import com.yexl.trading.coinbase.disruptor.DisruptorOrchestrator;
import com.yexl.trading.marketdata.metrics.LatencyTracker;
import com.yexl.trading.coinbase.monitor.BookMonitor;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.coinbase.recording.FrameRecorder;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import com.yexl.trading.marketdata.recovery.RecoverySettings;
import com.yexl.trading.coinbase.ws.CoinbaseWsClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Entry point. Wires config, credentials, Disruptor, WS client, and monitor.
 *
 * <p>Shutdown via Ctrl-C / SIGTERM triggers a shutdown hook that stops
 * components in reverse-startup order.
 */
public final class Main {

    private static final Logger log = LoggerFactory.getLogger(Main.class);

    public static void main(String[] args) {
        // A trading process should not phone home. Set before any Chronicle
        // class loads.
        System.setProperty("chronicle.analytics.disable", "true");
        try {
            AppConfig config = AppConfig.load();

            CdpCredentials credentials = CdpCredentials.load(config.apiKey, config.signingKeyPath);
            JwtSigner signer = new JwtSigner(
                    credentials, config.jwtTtlSeconds, config.jwtRefreshBeforeExpSeconds);
            // Force an initial sign — fail fast if the key is bad.
            signer.get();
            log.info("Initial JWT signed successfully");

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

            FrameRecorder frameRecorder = config.recordingEnabled
                    ? new FrameRecorder(config.recordingDir)
                    : null;

            CoinbaseWsClient wsClient = new CoinbaseWsClient(
                    config, signer, disruptor.disruptor().getRingBuffer(), recoveryManager, frameRecorder);
            recoveryManager.attachConnection(wsClient);

            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                log.info("Shutdown hook triggered");
                try {
                    monitor.close();
                } catch (Exception ignored) { }
                if (frameRecorder != null) {
                    try {
                        frameRecorder.close();
                    } catch (Exception ignored) { }
                }
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

            // Block until the channel is closed (or the JVM is killed).
            wsClient.awaitClose();
            log.info("WS channel closed; main thread exiting");
        } catch (Exception e) {
            log.error("Fatal startup error", e);
            System.exit(1);
        }
    }
}
