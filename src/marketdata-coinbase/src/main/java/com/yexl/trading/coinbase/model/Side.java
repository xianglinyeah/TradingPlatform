package com.yexl.trading.coinbase.model;

/**
 * Order book side.
 *
 * <p>Coinbase Advanced Trade l2_data actually sends {@code "bid"} / {@code "offer"}
 * (lowercase) in the {@code side} field of each update — confirmed against live
 * production data. {@code "ask"}/{@code "buy"}/{@code "sell"} are accepted too
 * for robustness, but were an unverified assumption, not something observed
 * on the wire.
 */
public enum Side {
    BID,
    ASK;

    public static Side fromString(String s) {
        if (s == null) {
            throw new IllegalArgumentException("Side string is null");
        }
        return switch (s.toLowerCase()) {
            case "bid", "buy" -> BID;
            case "ask", "offer", "sell" -> ASK;
            default -> throw new IllegalArgumentException("Unknown side: " + s);
        };
    }
}
