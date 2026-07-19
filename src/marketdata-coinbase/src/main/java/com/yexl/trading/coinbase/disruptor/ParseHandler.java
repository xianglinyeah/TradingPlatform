package com.yexl.trading.coinbase.disruptor;

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
import java.time.Instant;

/**
 * Disruptor Stage 2 — parses the raw WebSocket JSON on Thread 2.
 *
 * <p>Strategic choices:
 * <ul>
 *   <li>Jackson {@code readTree} returns {@link JsonNode} and lets us
 *       navigate without allocating POJOs. BigDecimal is constructed
 *       directly from the wire string via {@link BigDecimal#BigDecimal(String)},
 *       which is the precision-preserving way to parse decimal numbers.</li>
 *   <li>The {@link MarketDataEvent#updates} array is allocated fresh per
 *       frame because the size range is huge (1 for an incremental update
 *       vs. several thousand for a snapshot). Phase 2 may add a thread-local
 *       pool to reduce allocation on the hot incremental-update path.</li>
 *   <li>On parse failure the event is marked ERROR and the rawJson ref is
 *       still nulled so the string can be reclaimed.</li>
 *   <li>Every Coinbase frame carries a connection-wide {@code sequence_num}.
 *       This handler tracks the last one seen (a plain instance field — safe
 *       because this handler runs single-threaded) and reports forward gaps
 *       to {@link RecoveryManager}. A backward jump is treated as a fresh
 *       connection restarting its counter from zero and silently rebases the
 *       baseline rather than alerting.</li>
 * </ul>
 */
public final class ParseHandler implements EventHandler<MarketDataEvent> {

    private static final Logger log = LoggerFactory.getLogger(ParseHandler.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final RecoveryManager recoveryManager;

    /** -1 = no sequence number observed yet. Only ever touched on this handler's thread. */
    private long lastSequenceNum = -1L;

    public ParseHandler(RecoveryManager recoveryManager) {
        this.recoveryManager = recoveryManager;
    }

    @Override
    public void onEvent(MarketDataEvent event, long sequence, boolean endOfBatch) {
        if (event.rawJson == null) {
            return;
        }
        try {
            JsonNode root = MAPPER.readTree(event.rawJson);

            JsonNode channelNode = root.get("channel");
            event.channel = ChannelType.fromWire(channelNode != null ? channelNode.asText() : null);

            JsonNode seqNode = root.get("sequence_num");
            if (seqNode != null && seqNode.canConvertToLong()) {
                event.sequenceNum = seqNode.asLong();
                checkSequence(event.sequenceNum);
            }

            JsonNode tsNode = root.get("timestamp");
            event.exchangeTsNanos = tsNode != null ? parseIsoToNanos(tsNode.asText()) : 0L;

            switch (event.channel) {
                case L2_DATA -> parseL2(event, root);
                case HEARTBEATS -> parseHeartbeat(event, root);
                case SUBSCRIPTIONS -> parseSubscriptions(event, root);
                case ERROR -> {
                    event.messageType = EventMessageType.ERROR;
                    log.error("Server-side error frame: {}", event.rawJson);
                }
                default -> log.debug("Unhandled channel {} (raw dropped): {}",
                        event.channel, truncate(event.rawJson, 256));
            }
        } catch (Exception e) {
            log.error("Parse failed: {}", truncate(event.rawJson, 512), e);
            event.messageType = EventMessageType.ERROR;
        } finally {
            event.rawJson = null;
            event.parsedNanos = System.nanoTime();
        }
    }

    private void checkSequence(long actualSeq) {
        if (lastSequenceNum >= 0 && actualSeq > lastSequenceNum + 1) {
            recoveryManager.onSequenceGap(lastSequenceNum + 1, actualSeq);
        }
        // A backward/equal jump (actualSeq <= lastSequenceNum) means a new
        // connection restarted the counter — resync silently, no alert.
        lastSequenceNum = actualSeq;
    }

    private void parseL2(MarketDataEvent event, JsonNode root) {
        JsonNode eventsArray = root.get("events");
        if (eventsArray == null || !eventsArray.isArray() || eventsArray.isEmpty()) {
            log.warn("l2_data frame has no events[]: {}", truncate(event.rawJson, 256));
            event.messageType = EventMessageType.UNKNOWN;
            return;
        }

        // First pass: count updates so we allocate the array exactly once.
        int total = 0;
        for (JsonNode ev : eventsArray) {
            JsonNode updates = ev.get("updates");
            if (updates != null && updates.isArray()) {
                total += updates.size();
            }
        }
        if (total == 0) {
            log.debug("l2_data frame has no updates inside events[]");
            event.messageType = EventMessageType.UNKNOWN;
            return;
        }

        BookUpdate[] arr = new BookUpdate[total];
        for (int i = 0; i < total; i++) {
            arr[i] = new BookUpdate();
        }
        event.updates = arr;

        int idx = 0;
        boolean hasSnapshot = false;
        boolean hasUpdate = false;
        for (JsonNode ev : eventsArray) {
            JsonNode typeNode = ev.get("type");
            String typeStr = typeNode != null ? typeNode.asText() : "update";
            boolean isSnapshot = "snapshot".equalsIgnoreCase(typeStr);
            boolean isUpdate = "update".equalsIgnoreCase(typeStr);
            if (isSnapshot) {
                hasSnapshot = true;
            }
            if (isUpdate) {
                hasUpdate = true;
            }

            JsonNode productIdNode = ev.get("product_id");
            String productId = productIdNode != null ? productIdNode.asText() : null;

            JsonNode updatesArray = ev.get("updates");
            if (updatesArray == null || !updatesArray.isArray()) {
                continue;
            }
            for (JsonNode u : updatesArray) {
                // Isolated per update: one malformed entry (unknown side, bad
                // decimal, ...) must not discard the rest of the frame — that
                // would silently drop every other update/product sharing this
                // WS message, including a snapshot, with no recovery trigger
                // (sequence_num is still contiguous, so nothing else notices).
                try {
                    String sideStr = textOf(u.get("side"));
                    String priceStr = textOf(u.get("price_level"));
                    String qtyStr = textOf(u.get("new_quantity"));
                    long eventTimeNanos = parseIsoToNanos(textOf(u.get("event_time")));

                    arr[idx].set(
                            Side.fromString(sideStr),
                            productId,
                            new BigDecimal(priceStr),
                            new BigDecimal(qtyStr),
                            eventTimeNanos,
                            isSnapshot
                    );
                    idx++;
                } catch (Exception e) {
                    log.warn("Skipping malformed update (product={}): {}", productId, u, e);
                }
            }
        }

        event.updateCount = idx;

        if (hasSnapshot && hasUpdate) {
            // Unusual — Phase 1 treats this as a snapshot. The isSnapshot
            // flag on each BookUpdate is the authoritative routing signal.
            log.warn("Mixed snapshot+update in a single WS frame ({} updates) — "
                    + "routing by per-update isSnapshot flag", idx);
            event.messageType = EventMessageType.SNAPSHOT;
        } else if (hasSnapshot) {
            event.messageType = EventMessageType.SNAPSHOT;
        } else {
            event.messageType = EventMessageType.UPDATE;
        }
    }

    private void parseHeartbeat(MarketDataEvent event, JsonNode root) {
        event.messageType = EventMessageType.HEARTBEAT;
        JsonNode eventsArray = root.get("events");
        if (eventsArray == null || !eventsArray.isArray() || eventsArray.isEmpty()) {
            return;
        }
        JsonNode ev = eventsArray.get(0);
        JsonNode counter = ev.get("heartbeat_counter");
        if (counter != null && counter.canConvertToLong()) {
            event.heartbeatCounter = counter.asLong();
        }
    }

    private void parseSubscriptions(MarketDataEvent event, JsonNode root) {
        JsonNode typeNode = root.get("type");
        event.messageType = EventMessageType.fromString(
                typeNode != null ? typeNode.asText() : null);
        log.info("Subscription frame: {}", truncate(event.rawJson, 256));
    }

    private static String textOf(JsonNode node) {
        return node != null ? node.asText() : null;
    }

    private static long parseIsoToNanos(String iso8601) {
        if (iso8601 == null || iso8601.isBlank()) {
            return 0L;
        }
        try {
            // Examples observed from Coinbase:
            //   "1970-01-01T00:00:00Z"
            //   "2023-02-09T20:32:50.714964855Z"
            Instant inst = Instant.parse(iso8601);
            return inst.getEpochSecond() * 1_000_000_000L + inst.getNano();
        } catch (Exception e) {
            return 0L;
        }
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "<null>";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...(" + s.length() + " chars)";
    }
}
