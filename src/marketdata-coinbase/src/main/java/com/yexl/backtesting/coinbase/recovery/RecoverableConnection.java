package com.yexl.backtesting.coinbase.recovery;

import java.util.List;

/**
 * Narrow view of {@link com.yexl.backtesting.coinbase.ws.CoinbaseWsClient}
 * that {@link RecoveryManager} needs to drive recovery. Kept separate from
 * the full client so {@code RecoveryManager} doesn't depend on Netty types.
 */
public interface RecoverableConnection {

    /**
     * Tear down the current channel (if any) and re-establish the WS
     * connection: handshake, JWT, then resubscribe {@code level2} (all
     * configured products) + {@code heartbeats}. Blocking — intended to run
     * on {@link RecoveryManager}'s dedicated recovery thread, never on the
     * Netty I/O thread or a Disruptor handler thread.
     */
    void reconnect() throws Exception;

    /**
     * Send a fresh {@code level2} subscribe message for the given products on
     * the existing channel, without tearing down the connection. Coinbase
     * responds with a new snapshot for each product.
     */
    void resubscribeLevel2(List<String> productIds);
}
