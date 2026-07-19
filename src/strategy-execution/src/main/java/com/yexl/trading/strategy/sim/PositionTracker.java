package com.yexl.trading.strategy.sim;

/**
 * Simulated position and PnL for one product, average-cost accounting.
 * This is the paper-trading ledger only — the C# Execution.Service stays
 * authoritative for anything involving real money.
 *
 * <p>Doubles are deliberate: at sim order sizes (0.001 BTC, ~$65 notional)
 * PnL lives in cents and double error is orders of magnitude below fee
 * noise. The fills JSONL keeps exact decimal strings for later re-audit.
 *
 * <p>Written by the SimFillHandler thread; {@link #summary} is read by the
 * stats thread — methods are synchronized (fill rate is cooldown-gated,
 * contention is nil).
 */
public final class PositionTracker {

    private double position;
    private double avgCost;
    private double realizedPnl;
    private double feesPaid;
    private long fills;
    private long partialFills;
    /** Last mid from the sim book, for unrealized marking. */
    private volatile double lastMid = Double.NaN;

    /** @param signedQty +qty for a buy fill, -qty for a sell fill */
    public synchronized void onFill(double signedQty, double price, double fee, boolean partial) {
        feesPaid += fee;
        fills++;
        if (partial) {
            partialFills++;
        }
        if (position == 0 || Math.signum(position) == Math.signum(signedQty)) {
            double newAbs = Math.abs(position) + Math.abs(signedQty);
            avgCost = (avgCost * Math.abs(position) + price * Math.abs(signedQty)) / newAbs;
            position += signedQty;
            return;
        }
        // Opposite sign: close (part of) the existing position first.
        double closing = Math.min(Math.abs(signedQty), Math.abs(position));
        realizedPnl += (price - avgCost) * closing * Math.signum(position);
        double newPosition = position + signedQty;
        if (newPosition == 0) {
            avgCost = 0;
        } else if (Math.signum(newPosition) != Math.signum(position)) {
            // Flipped through zero: the residual opened at this fill's price.
            avgCost = price;
        }
        position = newPosition;
    }

    public void markMid(double mid) {
        lastMid = mid;
    }

    public synchronized String summary() {
        double mid = lastMid;
        double unrealized = Double.isNaN(mid) || position == 0 ? 0.0 : (mid - avgCost) * position;
        return String.format(
                "pos=%.6f avgCost=%.2f realized=%.4f unrealized=%.4f fees=%.4f net=%.4f fills=%d partial=%d",
                position, avgCost, realizedPnl, unrealized, feesPaid,
                realizedPnl + unrealized - feesPaid, fills, partialFills);
    }

    public synchronized double position() {
        return position;
    }

    public synchronized double realizedPnl() {
        return realizedPnl;
    }
}
