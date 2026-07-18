package com.yexl.backtesting.coinbase.model;

import java.math.BigDecimal;

/**
 * Immutable price level used in published order book snapshots.
 */
public record PriceLevel(BigDecimal price, BigDecimal qty) {
}
