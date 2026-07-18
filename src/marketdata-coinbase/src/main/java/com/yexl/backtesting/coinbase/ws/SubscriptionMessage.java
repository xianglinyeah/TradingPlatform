package com.yexl.backtesting.coinbase.ws;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;

/**
 * Builds a Coinbase Advanced Trade subscribe/unsubscribe payload.
 *
 * <pre>
 *   {
 *     "type": "subscribe",
 *     "channel": "level2",
 *     "product_ids": ["BTC-USD"],
 *     "jwt": "&lt;ES256 JWT&gt;"
 *   }
 * </pre>
 *
 * <p>The {@code heartbeats} channel does not require {@code product_ids}; pass
 * null for that case.
 */
public record SubscriptionMessage(String type, String channel, List<String> productIds, String jwt) {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public String toJson() {
        try {
            var node = MAPPER.createObjectNode();
            node.put("type", type);
            node.put("channel", channel);
            if (productIds != null && !productIds.isEmpty()) {
                node.set("product_ids", MAPPER.valueToTree(productIds));
            }
            if (jwt != null) {
                node.put("jwt", jwt);
            }
            return MAPPER.writeValueAsString(node);
        } catch (Exception e) {
            throw new RuntimeException("Failed to serialize SubscriptionMessage", e);
        }
    }
}
