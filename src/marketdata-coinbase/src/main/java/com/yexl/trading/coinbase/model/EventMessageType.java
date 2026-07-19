package com.yexl.trading.coinbase.model;

/**
 * Logical message type carried by a {@link MarketDataEvent}.
 *
 * <p>This is derived from the per-event {@code type} field on Coinbase l2_data
 * messages ({@code "snapshot"} / {@code "update"}), the channel-level type for
 * heartbeats, or the top-level {@code type} for subscription acks.
 */
public enum EventMessageType {
    SNAPSHOT,
    UPDATE,
    HEARTBEAT,
    SUBSCRIBED,
    UNSUBSCRIBED,
    ERROR,
    UNKNOWN;

    public static EventMessageType fromString(String s) {
        if (s == null) {
            return UNKNOWN;
        }
        return switch (s.toLowerCase()) {
            case "snapshot" -> SNAPSHOT;
            case "update" -> UPDATE;
            case "heartbeats", "heartbeat" -> HEARTBEAT;
            case "subscribed" -> SUBSCRIBED;
            case "unsubscribed" -> UNSUBSCRIBED;
            case "error" -> ERROR;
            default -> UNKNOWN;
        };
    }
}
