package com.yexl.backtesting.coinbase.model;

/**
 * Coinbase Advanced Trade WebSocket top-level {@code channel} field.
 *
 * <p>Note: for the level2 channel, the server actually emits {@code "l2_data"}
 * as the channel name on outbound messages (even though you subscribe as
 * {@code "level2"}).
 */
public enum ChannelType {
    L2_DATA("l2_data"),
    HEARTBEATS("heartbeats"),
    SUBSCRIPTIONS("subscriptions"),
    MARKET_TRADES("market_trades"),
    TICKER("ticker"),
    TICKER_BATCH("ticker_batch"),
    STATUS("status"),
    CANDLES("candles"),
    ERROR("error"),
    UNKNOWN("");

    private final String wireValue;

    ChannelType(String wireValue) {
        this.wireValue = wireValue;
    }

    public String wireValue() {
        return wireValue;
    }

    public static ChannelType fromWire(String s) {
        if (s == null) {
            return UNKNOWN;
        }
        for (ChannelType v : values()) {
            if (v.wireValue.equalsIgnoreCase(s)) {
                return v;
            }
        }
        return UNKNOWN;
    }
}
