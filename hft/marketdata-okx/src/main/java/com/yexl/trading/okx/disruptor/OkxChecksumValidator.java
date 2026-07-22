package com.yexl.trading.okx.disruptor;

import com.yexl.trading.marketdata.book.OrderBook;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.model.OrderBookSnapshot;
import com.yexl.trading.marketdata.model.PriceLevel;
import com.yexl.trading.marketdata.pipeline.BookIntegrityCheck;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.zip.CRC32;

/**
 * Verifies OKX's per-frame book checksum against the local replica, right
 * after the frame's updates are applied (runs on the OrderBookHandler
 * thread — see {@link BookIntegrityCheck}).
 *
 * <p>OKX algorithm: interleave the top-25 bid and ask levels as
 * {@code bid:ask:bid:ask...} pairs of {@code price:size} (continuing with
 * the longer side when one runs out), join everything with {@code ':'},
 * CRC32 the UTF-8 bytes, compare as signed int32.
 *
 * <p>Faithfulness: levels were parsed with {@code new BigDecimal(wireString)},
 * which preserves the exact scale, so {@code toPlainString()} reproduces the
 * wire text byte-for-byte (OKX never uses scientific notation).
 *
 * <p>Frames with {@code updateCount == 0} (the 60s no-change keepalive) are
 * skipped: the book is unchanged since the previous verified frame.
 *
 * <p>On mismatch: report {@link RecoveryManager#onBookCorruption} — same
 * response as a sequence gap (STALE + resubscribe for a fresh snapshot).
 */
public final class OkxChecksumValidator implements BookIntegrityCheck {

    private static final Logger log = LoggerFactory.getLogger(OkxChecksumValidator.class);
    private static final int DEPTH = 25;
    private static final long OK_LOG_EVERY = 1000;

    private final RecoveryManager recoveryManager;

    // Single-threaded (book handler thread) — reuse scratch objects.
    private final CRC32 crc = new CRC32();
    private final StringBuilder sb = new StringBuilder(1024);
    private long okCount;
    private long failCount;

    public OkxChecksumValidator(RecoveryManager recoveryManager) {
        this.recoveryManager = recoveryManager;
    }

    @Override
    public void afterApply(MarketDataEvent event, OrderBookManager manager) {
        if (!event.bookChecksumPresent || event.updateCount == 0 || event.updates == null) {
            return;
        }
        String instId = event.updates[0].productId;
        if (instId == null) {
            return;
        }
        OrderBook book = manager.get(instId);
        if (book == null || !book.isSnapshotInitialized()) {
            return;
        }

        OrderBookSnapshot snap = book.snapshot(DEPTH);
        List<PriceLevel> bids = snap.bids();
        List<PriceLevel> asks = snap.asks();

        sb.setLength(0);
        int n = Math.max(bids.size(), asks.size());
        for (int i = 0; i < n; i++) {
            if (i < bids.size()) {
                appendLevel(bids.get(i));
            }
            if (i < asks.size()) {
                appendLevel(asks.get(i));
            }
        }

        crc.reset();
        crc.update(sb.toString().getBytes(StandardCharsets.UTF_8));
        int computed = (int) crc.getValue();

        if (computed == event.bookChecksum) {
            if (++okCount % OK_LOG_EVERY == 0) {
                log.info("[{}] book checksum verified ({} ok, {} failed this process)",
                        instId, okCount, failCount);
            }
        } else {
            failCount++;
            log.error("[{}] BOOK CHECKSUM MISMATCH: wire={} computed={} (top-{}, seqId={}) — resubscribing",
                    instId, event.bookChecksum, computed, DEPTH, event.sequenceNum);
            recoveryManager.onBookCorruption(instId + "-checksum");
        }
    }

    private void appendLevel(PriceLevel lvl) {
        if (sb.length() > 0) {
            sb.append(':');
        }
        sb.append(lvl.price().toPlainString()).append(':').append(lvl.qty().toPlainString());
    }
}
