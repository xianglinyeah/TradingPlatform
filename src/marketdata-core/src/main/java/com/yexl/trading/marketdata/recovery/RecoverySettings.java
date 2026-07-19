package com.yexl.trading.marketdata.recovery;

import java.util.List;

/**
 * Venue-neutral knobs for {@link RecoveryManager}. Each venue module builds
 * one from its own config — this is what keeps the recovery orchestration
 * free of any per-venue config class.
 */
public final class RecoverySettings {

    public final long heartbeatExpectedIntervalMs;
    public final int heartbeatMissedThreshold;
    public final long reconnectInitialBackoffMs;
    public final long reconnectMaxBackoffMs;
    public final List<String> productIds;

    public RecoverySettings(long heartbeatExpectedIntervalMs, int heartbeatMissedThreshold,
                            long reconnectInitialBackoffMs, long reconnectMaxBackoffMs,
                            List<String> productIds) {
        this.heartbeatExpectedIntervalMs = heartbeatExpectedIntervalMs;
        this.heartbeatMissedThreshold = heartbeatMissedThreshold;
        this.reconnectInitialBackoffMs = reconnectInitialBackoffMs;
        this.reconnectMaxBackoffMs = reconnectMaxBackoffMs;
        this.productIds = List.copyOf(productIds);
    }
}
