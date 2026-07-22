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
    /** Proactive full-resnapshot cadence, independent of any error trigger — bounds how
     * long a downstream consumer's book replica can go without an authoritative re-ground
     * against the exchange's own state. 0 disables it. */
    public final long resnapshotIntervalMs;

    public RecoverySettings(long heartbeatExpectedIntervalMs, int heartbeatMissedThreshold,
                            long reconnectInitialBackoffMs, long reconnectMaxBackoffMs,
                            List<String> productIds) {
        this(heartbeatExpectedIntervalMs, heartbeatMissedThreshold,
                reconnectInitialBackoffMs, reconnectMaxBackoffMs, productIds, 0L);
    }

    public RecoverySettings(long heartbeatExpectedIntervalMs, int heartbeatMissedThreshold,
                            long reconnectInitialBackoffMs, long reconnectMaxBackoffMs,
                            List<String> productIds, long resnapshotIntervalMs) {
        this.heartbeatExpectedIntervalMs = heartbeatExpectedIntervalMs;
        this.heartbeatMissedThreshold = heartbeatMissedThreshold;
        this.reconnectInitialBackoffMs = reconnectInitialBackoffMs;
        this.reconnectMaxBackoffMs = reconnectMaxBackoffMs;
        this.productIds = List.copyOf(productIds);
        this.resnapshotIntervalMs = resnapshotIntervalMs;
    }
}
