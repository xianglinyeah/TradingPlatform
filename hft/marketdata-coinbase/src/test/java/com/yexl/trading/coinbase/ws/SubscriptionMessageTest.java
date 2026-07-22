package com.yexl.trading.coinbase.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SubscriptionMessageTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void serializesTypeChannelProductsAndJwt() throws Exception {
        SubscriptionMessage msg = new SubscriptionMessage(
                "subscribe", "level2", List.of("BTC-USD", "ETH-USD"), "the.jwt.token");

        JsonNode node = MAPPER.readTree(msg.toJson());

        assertEquals("subscribe", node.get("type").asText());
        assertEquals("level2", node.get("channel").asText());
        assertEquals("the.jwt.token", node.get("jwt").asText());
        List<String> products = MAPPER.convertValue(node.get("product_ids"),
                MAPPER.getTypeFactory().constructCollectionType(List.class, String.class));
        assertEquals(List.of("BTC-USD", "ETH-USD"), products);
    }

    @Test
    void omitsProductIdsFieldForHeartbeatsChannel() throws Exception {
        SubscriptionMessage msg = new SubscriptionMessage("subscribe", "heartbeats", null, "jwt");

        JsonNode node = MAPPER.readTree(msg.toJson());

        assertFalse(node.has("product_ids"));
        assertTrue(node.has("jwt"));
    }

    @Test
    void omitsJwtFieldWhenNull() throws Exception {
        SubscriptionMessage msg = new SubscriptionMessage("unsubscribe", "level2", List.of("BTC-USD"), null);

        JsonNode node = MAPPER.readTree(msg.toJson());

        assertFalse(node.has("jwt"));
        assertTrue(node.has("product_ids"));
    }
}
