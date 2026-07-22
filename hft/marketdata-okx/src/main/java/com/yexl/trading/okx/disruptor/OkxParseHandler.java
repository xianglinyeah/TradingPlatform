package com.yexl.trading.okx.disruptor;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lmax.disruptor.EventHandler;
import com.yexl.trading.marketdata.model.BookUpdate;
import com.yexl.trading.marketdata.model.ChannelType;
import com.yexl.trading.marketdata.model.EventMessageType;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.model.Side;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

/**
 * Disruptor Stage 2 — parses OKX v5 {@code books} frames on Thread 2 into the
 * same venue-neutral {@link MarketDataEvent} shape the core pipeline consumes
 * (channel mapped to {@link ChannelType#L2_DATA}, so OrderBookHandler and
 * ChroniclePublishHandler need no OKX awareness).
 *
 * <p>Wire format:
 * <pre>
 *   {"arg":{"channel":"books","instId":"BTC-USDT"},
 *    "action":"snapshot"|"update",
 *    "data":[{"asks":[["price","size","0","numOrders"],...],
 *             "bids":[...], "ts":"1629966436396",
 *             "seqId":123, "prevSeqId":122, "checksum":-855196043}]}
 * </pre>
 *
 * <p>Sequence integrity is per-instrument, not connection-wide like Coinbase:
 * each update's {@code prevSeqId} must equal the last seen {@code seqId} for
 * that instId. A forward mismatch is a real gap → {@link RecoveryManager}
 * (which resubscribes; only a fresh subscribe re-delivers a snapshot). A
 * backward jump is a server-side seq reset (post-maintenance) and rebases
 * silently. OKX's 60s keepalive push repeats {@code seqId == prevSeqId},
 * which passes the equality check by construction.
 *
 * <p>The per-frame {@code checksum} is carried onto the event and verified
 * post-apply by {@link OkxChecksumValidator} (BigDecimal preserves the wire
 * string's exact scale, so top-25 reconstruction is faithful).
 */
public final class OkxParseHandler implements EventHandler<MarketDataEvent> {

    private static final Logger log = LoggerFactory.getLogger(OkxParseHandler.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final RecoveryManager recoveryManager;

    /** Last seqId per instId. Single-threaded handler — no synchronization. */
    private final Map<String, Long> lastSeqId = new HashMap<>();


    public OkxParseHandler(RecoveryManager recoveryManager) {
        this.recoveryManager = recoveryManager;
    }

    @Override
    public void onEvent(MarketDataEvent event, long sequence, boolean endOfBatch) {
        String raw = event.rawJson;
        if (raw == null) {
            return;
        }
        try {
            // OKX answers the client's "ping" with a bare (non-JSON) "pong".
            if ("pong".equals(raw)) {
                event.channel = ChannelType.HEARTBEATS;
                event.messageType = EventMessageType.HEARTBEAT;
                return;
            }

            JsonNode root = MAPPER.readTree(raw);

            JsonNode eventNode = root.get("event");
            if (eventNode != null) {
                parseEventFrame(event, eventNode.asText(), root);
                return;
            }

            JsonNode arg = root.get("arg");
            String channel = arg != null && arg.get("channel") != null ? arg.get("channel").asText() : null;
            if ("books".equals(channel)) {
                event.channel = ChannelType.L2_DATA;
                parseBooks(event, arg, root);
            } else {
                log.debug("Unhandled channel {} (raw dropped): {}", channel, truncate(raw, 256));
            }
        } catch (Exception e) {
            log.error("Parse failed: {}", truncate(raw, 512), e);
            event.messageType = EventMessageType.ERROR;
        } finally {
            event.rawJson = null;
            event.parsedNanos = System.nanoTime();
        }
    }

    private void parseEventFrame(MarketDataEvent event, String type, JsonNode root) {
        switch (type) {
            case "subscribe" -> {
                event.channel = ChannelType.SUBSCRIPTIONS;
                event.messageType = EventMessageType.SUBSCRIBED;
                log.info("Subscribe ack: {}", root.get("arg"));
            }
            case "unsubscribe" -> {
                event.channel = ChannelType.SUBSCRIPTIONS;
                event.messageType = EventMessageType.UNSUBSCRIBED;
                log.info("Unsubscribe ack: {}", root.get("arg"));
            }
            case "error" -> {
                event.channel = ChannelType.ERROR;
                event.messageType = EventMessageType.ERROR;
                log.error("Server-side error frame: {}", root);
            }
            default -> log.debug("Unhandled event frame type: {}", type);
        }
    }

    private void parseBooks(MarketDataEvent event, JsonNode arg, JsonNode root) {
        String instId = arg.get("instId") != null ? arg.get("instId").asText() : null;
        JsonNode dataArray = root.get("data");
        if (instId == null || dataArray == null || !dataArray.isArray() || dataArray.isEmpty()) {
            log.warn("books frame missing instId/data: {}", truncate(root.toString(), 256));
            event.messageType = EventMessageType.UNKNOWN;
            return;
        }
        boolean isSnapshot = "snapshot".equals(
                root.get("action") != null ? root.get("action").asText() : "update");

        // OKX documents data as a one-element array for books; guard loudly
        // in case that ever changes, since entries past [0] would be dropped.
        if (dataArray.size() > 1) {
            log.warn("[{}] books frame with {} data entries — only the first is processed",
                    instId, dataArray.size());
        }
        JsonNode data = dataArray.get(0);

        JsonNode tsNode = data.get("ts");
        if (tsNode != null) {
            event.exchangeTsNanos = tsNode.asLong() * 1_000_000L; // epoch millis -> nanos
        }

        long seqId = data.get("seqId") != null ? data.get("seqId").asLong() : -1L;
        long prevSeqId = data.get("prevSeqId") != null ? data.get("prevSeqId").asLong() : -1L;
        event.sequenceNum = seqId;
        checkSequence(instId, isSnapshot, seqId, prevSeqId);

        // checksum == 0 is OKX's "not computed" sentinel (a real CRC32 of 0
        // is a 2^-32 event). Observed live: some sessions carry real
        // checksums on every update (1000+ consecutive verifications passed),
        // others send 0 on every frame for extended stretches — verification
        // is therefore opportunistic. Treating 0 as a value caused a
        // false-mismatch → resubscribe → fresh 0-checksum snapshot storm.
        JsonNode checksumNode = data.get("checksum");
        if (checksumNode != null && checksumNode.canConvertToInt() && checksumNode.asInt() != 0) {
            event.bookChecksum = checksumNode.asInt();
            event.bookChecksumPresent = true;
        }

        JsonNode bids = data.get("bids");
        JsonNode asks = data.get("asks");
        int total = (bids != null ? bids.size() : 0) + (asks != null ? asks.size() : 0);
        if (total == 0) {
            // Legal: OKX's 60s no-change keepalive carries empty sides.
            event.messageType = isSnapshot ? EventMessageType.SNAPSHOT : EventMessageType.UPDATE;
            event.updateCount = 0;
            return;
        }

        BookUpdate[] arr = new BookUpdate[total];
        for (int i = 0; i < total; i++) {
            arr[i] = new BookUpdate();
        }
        event.updates = arr;

        int idx = 0;
        idx = parseSide(arr, idx, bids, Side.BID, instId, event.exchangeTsNanos, isSnapshot);
        idx = parseSide(arr, idx, asks, Side.ASK, instId, event.exchangeTsNanos, isSnapshot);
        event.updateCount = idx;
        event.messageType = isSnapshot ? EventMessageType.SNAPSHOT : EventMessageType.UPDATE;
    }

    /** Levels arrive as {@code ["price","size","0","numOrders"]}; size "0" removes the level. */
    private int parseSide(BookUpdate[] arr, int idx, JsonNode levels, Side side,
                          String instId, long tsNanos, boolean isSnapshot) {
        if (levels == null || !levels.isArray()) {
            return idx;
        }
        for (JsonNode level : levels) {
            // Isolated per level — one malformed entry must not drop the rest
            // of the frame (same rationale as the Coinbase parser).
            try {
                arr[idx].set(
                        side,
                        instId,
                        new BigDecimal(level.get(0).asText()),
                        new BigDecimal(level.get(1).asText()),
                        tsNanos,
                        isSnapshot
                );
                idx++;
            } catch (Exception e) {
                log.warn("Skipping malformed level (instId={}): {}", instId, level, e);
            }
        }
        return idx;
    }

    private void checkSequence(String instId, boolean isSnapshot, long seqId, long prevSeqId) {
        if (seqId < 0) {
            return;
        }
        if (isSnapshot) {
            // Fresh baseline (initial subscribe or post-gap resubscribe).
            lastSeqId.put(instId, seqId);
            return;
        }
        Long last = lastSeqId.get(instId);
        if (last != null && prevSeqId >= 0 && prevSeqId != last) {
            if (prevSeqId > last) {
                recoveryManager.onSequenceGap(last + 1, prevSeqId);
            } else {
                log.info("[{}] seqId rebased {} -> {} (server-side seq reset)", instId, last, seqId);
            }
        }
        lastSeqId.put(instId, seqId);
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "<null>";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...(" + s.length() + " chars)";
    }
}
