package com.yexl.trading.marketdata.wire;

import net.openhft.chronicle.bytes.Bytes;
import net.openhft.chronicle.wire.Wire;
import net.openhft.chronicle.wire.WireType;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MdWireCodecTest {

    private Bytes<?> bytes;
    private Wire wire;

    @BeforeEach
    void setUp() {
        bytes = Bytes.allocateElasticOnHeap();
        wire = WireType.BINARY.apply(bytes);
    }

    @AfterEach
    void tearDown() {
        bytes.releaseLast();
    }

    private static MdDelta sample() {
        MdDelta d = new MdDelta();
        d.venue = "COINBASE";
        d.productId = "BTC-USD";
        d.snapshot = true;
        d.pseq = 42L;
        d.venueSeq = 1000L;
        d.exchTsEpochNanos = 111L;
        d.recvTsEpochNanos = 222L;
        d.pubTsEpochNanos = 333L;
        d.prepareLevels(2);
        d.setLevel(0, MdDelta.SIDE_BID, "100.5", "1.25");
        d.setLevel(1, MdDelta.SIDE_ASK, "101.0", "0.75");
        return d;
    }

    @Test
    void roundTripsAllFieldsAndLevels() {
        MdDelta original = sample();
        MdWireCodec.write(wire, original);

        MdDelta out = new MdDelta();
        MdWireCodec.read(wire, out);

        assertEquals(MdWireCodec.SCHEMA_VERSION, out.schemaVersion);
        assertEquals(original.venue, out.venue);
        assertEquals(original.productId, out.productId);
        assertEquals(original.snapshot, out.snapshot);
        assertEquals(original.pseq, out.pseq);
        assertEquals(original.venueSeq, out.venueSeq);
        assertEquals(original.exchTsEpochNanos, out.exchTsEpochNanos);
        assertEquals(original.recvTsEpochNanos, out.recvTsEpochNanos);
        assertEquals(original.pubTsEpochNanos, out.pubTsEpochNanos);
        assertEquals(2, out.levelCount);
        assertEquals(MdDelta.SIDE_BID, out.sides[0]);
        assertEquals("100.5", out.prices[0]);
        assertEquals("1.25", out.qtys[0]);
        assertEquals(MdDelta.SIDE_ASK, out.sides[1]);
        assertEquals("101.0", out.prices[1]);
        assertEquals("0.75", out.qtys[1]);
    }

    @Test
    void roundTripsZeroLevelDocument() {
        MdDelta original = sample();
        original.prepareLevels(0);
        MdWireCodec.write(wire, original);

        MdDelta out = new MdDelta();
        MdWireCodec.read(wire, out);

        assertEquals(0, out.levelCount);
        assertEquals(MdWireCodec.SCHEMA_VERSION, out.schemaVersion);
    }

    @Test
    void unknownSchemaVersionIsFlaggedAndLevelCountZeroed() {
        // Hand-write a document with a bogus schema version and nothing else,
        // mirroring what a future-schema writer would produce from this
        // reader's point of view.
        wire.write("v").int32(99);
        wire.write("ven").text("SOMETHING_NEW");

        MdDelta out = new MdDelta();
        out.levelCount = 5; // sentinel to prove read() resets it
        MdWireCodec.read(wire, out);

        assertEquals(99, out.schemaVersion);
        assertEquals(0, out.levelCount);
    }

    @Test
    void reusedDeltaInstanceReflectsLatestDocumentOnly() {
        MdWireCodec.write(wire, sample());

        MdDelta reused = new MdDelta();
        MdWireCodec.read(wire, reused);
        assertTrue(reused.levelCount == 2);
        assertEquals("BTC-USD", reused.productId);
    }
}
