package com.yexl.trading.marketdata.wire;

import net.openhft.chronicle.wire.WireIn;
import net.openhft.chronicle.wire.WireOut;

/**
 * The one and only codec for market-data queue documents. Producer
 * (marketdata-coinbase) and consumers (strategy-execution, QueueTailer)
 * both go through this class, so the write and read sides cannot drift.
 *
 * <p><b>Schema v1</b> field order (self-describing wire, but written and read
 * in this order):
 * <pre>
 *   v       int32   schema version
 *   ven     text    venue tag ("COINBASE")
 *   prd     text    product id ("BTC-USD")
 *   snap    bool    snapshot flag (consumer: clear book, reload)
 *   pseq    int64   publisher-assigned dense sequence (continuity check)
 *   seq     int64   venue sequence (informational; not dense in the queue)
 *   exchTs  int64   exchange timestamp, epoch nanos (0 if absent)
 *   recvTs  int64   WS receive, epoch nanos
 *   pubTs   int64   publish, epoch nanos
 *   n       int32   level count
 *   n × { s int8 (0=bid,1=ask), p text (price), q text (qty) }
 * </pre>
 * Only epoch timestamps travel on the wire: {@code System.nanoTime()} origins
 * are not comparable across JVMs.
 *
 * <p>Schema evolution rule: any change to field set, order, or semantics bumps
 * {@link #SCHEMA_VERSION}; readers must check {@link MdDelta#schemaVersion}
 * after {@link #read} and skip (not guess at) versions they don't know.
 */
public final class MdWireCodec {

    public static final int SCHEMA_VERSION = 1;

    private MdWireCodec() { }

    public static void write(WireOut w, MdDelta d) {
        w.write("v").int32(SCHEMA_VERSION);
        w.write("ven").text(d.venue);
        w.write("prd").text(d.productId);
        w.write("snap").bool(d.snapshot);
        w.write("pseq").int64(d.pseq);
        w.write("seq").int64(d.venueSeq);
        w.write("exchTs").int64(d.exchTsEpochNanos);
        w.write("recvTs").int64(d.recvTsEpochNanos);
        w.write("pubTs").int64(d.pubTsEpochNanos);
        w.write("n").int32(d.levelCount);
        for (int i = 0; i < d.levelCount; i++) {
            w.write("s").int8(d.sides[i]);
            w.write("p").text(d.prices[i]);
            w.write("q").text(d.qtys[i]);
        }
    }

    /**
     * Decode one document into {@code d} (reused across calls). Always fills
     * {@link MdDelta#schemaVersion}; if it isn't {@link #SCHEMA_VERSION} the
     * rest of {@code d} is untouched garbage and the caller must skip the doc.
     */
    public static void read(WireIn w, MdDelta d) {
        d.schemaVersion = w.read("v").int32();
        if (d.schemaVersion != SCHEMA_VERSION) {
            d.levelCount = 0;
            return;
        }
        d.venue = w.read("ven").text();
        d.productId = w.read("prd").text();
        d.snapshot = w.read("snap").bool();
        d.pseq = w.read("pseq").int64();
        d.venueSeq = w.read("seq").int64();
        d.exchTsEpochNanos = w.read("exchTs").int64();
        d.recvTsEpochNanos = w.read("recvTs").int64();
        d.pubTsEpochNanos = w.read("pubTs").int64();
        int n = w.read("n").int32();
        d.prepareLevels(n);
        for (int i = 0; i < n; i++) {
            d.sides[i] = w.read("s").int8();
            d.prices[i] = w.read("p").text();
            d.qtys[i] = w.read("q").text();
        }
    }
}
