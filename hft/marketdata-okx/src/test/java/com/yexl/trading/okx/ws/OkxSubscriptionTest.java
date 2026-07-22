package com.yexl.trading.okx.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class OkxSubscriptionTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void serializesOneArgEntryPerInstrument() throws Exception {
        OkxSubscription sub = new OkxSubscription("subscribe", "books", List.of("BTC-USDT", "ETH-USDT"));

        JsonNode node = MAPPER.readTree(sub.toJson());

        assertEquals("subscribe", node.get("op").asText());
        JsonNode args = node.get("args");
        assertEquals(2, args.size());
        assertEquals("books", args.get(0).get("channel").asText());
        assertEquals("BTC-USDT", args.get(0).get("instId").asText());
        assertEquals("books", args.get(1).get("channel").asText());
        assertEquals("ETH-USDT", args.get(1).get("instId").asText());
    }

    @Test
    void singleInstrumentProducesSingleArgEntry() throws Exception {
        OkxSubscription sub = new OkxSubscription("unsubscribe", "books", List.of("BTC-USDT"));

        JsonNode node = MAPPER.readTree(sub.toJson());

        assertEquals(1, node.get("args").size());
    }
}
