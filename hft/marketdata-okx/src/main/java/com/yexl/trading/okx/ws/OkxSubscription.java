package com.yexl.trading.okx.ws;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.util.List;

/**
 * Builds an OKX v5 subscribe/unsubscribe payload — one arg per instrument:
 *
 * <pre>
 *   {
 *     "op": "subscribe",
 *     "args": [
 *       {"channel": "books", "instId": "BTC-USDT"},
 *       {"channel": "books", "instId": "ETH-USDT"}
 *     ]
 *   }
 * </pre>
 */
public record OkxSubscription(String op, String channel, List<String> instIds) {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public String toJson() {
        try {
            ObjectNode node = MAPPER.createObjectNode();
            node.put("op", op);
            ArrayNode args = node.putArray("args");
            for (String instId : instIds) {
                ObjectNode arg = args.addObject();
                arg.put("channel", channel);
                arg.put("instId", instId);
            }
            return MAPPER.writeValueAsString(node);
        } catch (Exception e) {
            throw new RuntimeException("Failed to serialize OkxSubscription", e);
        }
    }
}
