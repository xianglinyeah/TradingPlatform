package com.yexl.trading.strategy.handlers;

import com.lmax.disruptor.EventHandler;
import com.lmax.disruptor.LifecycleAware;
import com.yexl.trading.strategy.StrategyEvent;
import net.openhft.chronicle.queue.ChronicleQueue;
import net.openhft.chronicle.queue.ExcerptAppender;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Signal audit trail: every generated signal (pre-risk — this is the
 * conceptual Strategy→Execution boundary) is appended to a Chronicle Queue.
 *
 * <p>Nobody consumes this queue in-process. It exists as (1) a durable
 * audit/replay record and (2) the pre-reserved seam where Execution would be
 * split back out into its own process if multi-strategy topology ever
 * requires it. It runs on its own handler thread, gated only on
 * SignalHandler — deliberately parallel to the risk→placement chain so an
 * audit write can never delay an order.
 */
public final class AuditHandler
        implements EventHandler<StrategyEvent>, LifecycleAware, AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(AuditHandler.class);

    private final ChronicleQueue queue;
    private ExcerptAppender appender;
    private final AtomicLong audited = new AtomicLong();

    public AuditHandler(String auditQueueDir) {
        this.queue = ChronicleQueue.singleBuilder(auditQueueDir).build();
        log.info("Audit queue opened: {}", queue.file().getAbsolutePath());
    }

    @Override
    public void onStart() {
        appender = queue.createAppender();
    }

    @Override
    public void onShutdown() { }

    @Override
    public void onEvent(StrategyEvent event, long sequence, boolean endOfBatch) {
        if (event.arbSignal) {
            appender.writeDocument(w -> {
                w.write("v").int32(2);
                w.write("ts").int64(event.consumeEpochNanos);
                w.write("sym").text(event.arbSymbol);
                w.write("dev").float64(event.arbDevBps);
                w.write("ema").float64(event.arbEmaBps);
                w.write("bVen").text(event.arbBuyLeg.venue);
                w.write("bPrd").text(event.arbBuyLeg.productId);
                w.write("bPx").text(event.arbBuyLeg.touchPrice);
                w.write("sVen").text(event.arbSellLeg.venue);
                w.write("sPrd").text(event.arbSellLeg.productId);
                w.write("sPx").text(event.arbSellLeg.touchPrice);
                w.write("qty").text(event.arbBuyLeg.qty.toPlainString());
            });
            audited.incrementAndGet();
            return;
        }
        if (event.signal == StrategyEvent.SIGNAL_NONE) {
            return;
        }
        appender.writeDocument(w -> {
            w.write("v").int32(1);
            w.write("ts").int64(event.consumeEpochNanos);
            w.write("ven").text(event.delta.venue);
            w.write("prd").text(event.delta.productId);
            w.write("sig").int8((byte) event.signal);
            w.write("imb").float64(event.imbalance);
            w.write("px").text(event.touchPrice != null ? event.touchPrice : "");
            w.write("srcPseq").int64(event.delta.pseq);
        });
        audited.incrementAndGet();
    }

    public long auditedCount() {
        return audited.get();
    }

    @Override
    public void close() {
        queue.close();
        log.info("Audit queue closed ({} signals)", audited.get());
    }
}
