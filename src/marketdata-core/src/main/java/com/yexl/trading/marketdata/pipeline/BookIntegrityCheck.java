package com.yexl.trading.marketdata.pipeline;

import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.model.MarketDataEvent;

/**
 * Optional venue-specific post-apply book integrity hook (e.g. OKX's CRC32
 * book checksums — Coinbase has no equivalent and passes null).
 *
 * <p>Invoked by {@link OrderBookHandler} on its own handler thread right
 * after an event's updates are applied, so implementations may keep
 * unsynchronized per-thread state. Implementations report corruption to
 * {@code RecoveryManager.onBookCorruption} rather than throwing.
 */
public interface BookIntegrityCheck {

    void afterApply(MarketDataEvent event, OrderBookManager manager);
}
