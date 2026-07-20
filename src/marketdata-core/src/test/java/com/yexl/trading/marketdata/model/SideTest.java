package com.yexl.trading.marketdata.model;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class SideTest {

    @Test
    void mapsKnownBidSynonyms() {
        assertEquals(Side.BID, Side.fromString("bid"));
        assertEquals(Side.BID, Side.fromString("buy"));
        assertEquals(Side.BID, Side.fromString("BID"));
    }

    @Test
    void mapsKnownAskSynonyms() {
        assertEquals(Side.ASK, Side.fromString("ask"));
        assertEquals(Side.ASK, Side.fromString("offer"));
        assertEquals(Side.ASK, Side.fromString("sell"));
        assertEquals(Side.ASK, Side.fromString("OFFER"));
    }

    @Test
    void unknownStringThrows() {
        assertThrows(IllegalArgumentException.class, () -> Side.fromString("left"));
    }

    @Test
    void nullThrows() {
        assertThrows(IllegalArgumentException.class, () -> Side.fromString(null));
    }
}
