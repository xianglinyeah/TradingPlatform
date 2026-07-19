package com.yexl.trading.okx.disruptor;

import com.lmax.disruptor.ExceptionHandler;
import com.lmax.disruptor.dsl.Disruptor;
import com.lmax.disruptor.dsl.ProducerType;
import com.lmax.disruptor.util.DaemonThreadFactory;
import com.yexl.trading.marketdata.book.OrderBookManager;
import com.yexl.trading.marketdata.metrics.LatencyTracker;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.pipeline.ChroniclePublishHandler;
import com.yexl.trading.marketdata.pipeline.OrderBookHandler;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import com.yexl.trading.okx.config.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Wires the OKX handler chain — identical topology to the Coinbase module,
 * with only the parse stage venue-specific:
 *
 * <pre>
 *   Thread 1 (WS I/O)  --publish--&gt;
 *     RingBuffer&lt;MarketDataEvent&gt;
 *       --&gt; OkxParseHandler         (Thread 2: JSON -&gt; BookUpdate[])
 *       --&gt; OrderBookHandler        (Thread 3: apply to in-memory books)
 *       --&gt; ChroniclePublishHandler (Thread 4: normalized deltas out, optional)
 * </pre>
 */
public final class DisruptorOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(DisruptorOrchestrator.class);

    private final Disruptor<MarketDataEvent> disruptor;
    /** Null when chronicle.publish.enabled=false. */
    private final ChroniclePublishHandler publishHandler;

    public DisruptorOrchestrator(AppConfig config, OrderBookManager manager, RecoveryManager recoveryManager,
                                 LatencyTracker latencyTracker) {
        this.disruptor = new Disruptor<>(
                MarketDataEvent.FACTORY,
                config.ringBufferSize,
                DaemonThreadFactory.INSTANCE,
                ProducerType.SINGLE,
                config.waitStrategy
        );

        OkxParseHandler parseHandler = new OkxParseHandler(recoveryManager);
        OrderBookHandler bookHandler = new OrderBookHandler(manager, recoveryManager, latencyTracker,
                config.checksumEnabled ? new OkxChecksumValidator(recoveryManager) : null);

        if (config.chroniclePublishEnabled) {
            this.publishHandler = new ChroniclePublishHandler(
                    config.chronicleQueueDir, config.venue, manager, latencyTracker);
            disruptor.handleEventsWith(parseHandler).then(bookHandler).then(publishHandler);
        } else {
            this.publishHandler = null;
            disruptor.handleEventsWith(parseHandler).then(bookHandler);
        }

        disruptor.setDefaultExceptionHandler(new ExceptionHandler<>() {
            @Override
            public void handleEventException(Throwable ex, long sequence, MarketDataEvent event) {
                log.error("Disruptor handler exception at sequence={} channel={} messageType={}",
                        sequence, event.channel, event.messageType, ex);
            }

            @Override
            public void handleOnStartException(Throwable ex) {
                log.error("Disruptor failed to start", ex);
            }

            @Override
            public void handleOnShutdownException(Throwable ex) {
                log.error("Disruptor failed to shut down cleanly", ex);
            }
        });
    }

    public Disruptor<MarketDataEvent> disruptor() {
        return disruptor;
    }

    public void start() {
        log.info("Starting Disruptor (ringSize={})", disruptor.getRingBuffer().getBufferSize());
        disruptor.start();
        log.info("Disruptor started");
    }

    public void shutdown() {
        log.info("Shutting down Disruptor");
        disruptor.shutdown();
        if (publishHandler != null) {
            publishHandler.close();
        }
        log.info("Disruptor stopped");
    }
}
