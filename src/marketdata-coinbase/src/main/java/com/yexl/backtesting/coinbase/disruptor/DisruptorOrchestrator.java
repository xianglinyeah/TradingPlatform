package com.yexl.backtesting.coinbase.disruptor;

import com.lmax.disruptor.ExceptionHandler;
import com.lmax.disruptor.dsl.Disruptor;
import com.lmax.disruptor.dsl.ProducerType;
import com.lmax.disruptor.util.DaemonThreadFactory;
import com.yexl.backtesting.coinbase.config.AppConfig;
import com.yexl.backtesting.coinbase.metrics.LatencyTracker;
import com.yexl.backtesting.coinbase.model.MarketDataEvent;
import com.yexl.backtesting.coinbase.orderbook.OrderBookManager;
import com.yexl.backtesting.coinbase.recovery.RecoveryManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Wires up the LMAX Disruptor with a two-stage handler chain:
 *
 * <pre>
 *   Thread 1 (WS I/O)  --publish--&gt;
 *     RingBuffer&lt;MarketDataEvent&gt;
 *       --&gt; ParseHandler    (Thread 2: JSON -&gt; BookUpdate[])
 *       --&gt; OrderBookHandler (Thread 3: apply to in-memory books)
 * </pre>
 *
 * <p>Single-producer (Thread 1) lets Disruptor skip CAS on publish.
 */
public final class DisruptorOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(DisruptorOrchestrator.class);

    private final Disruptor<MarketDataEvent> disruptor;

    public DisruptorOrchestrator(AppConfig config, OrderBookManager manager, RecoveryManager recoveryManager,
                                 LatencyTracker latencyTracker) {
        this.disruptor = new Disruptor<>(
                MarketDataEvent.FACTORY,
                config.ringBufferSize,
                DaemonThreadFactory.INSTANCE,
                ProducerType.SINGLE,
                config.waitStrategy
        );

        ParseHandler parseHandler = new ParseHandler(recoveryManager);
        OrderBookHandler bookHandler = new OrderBookHandler(manager, recoveryManager, latencyTracker);

        disruptor.handleEventsWith(parseHandler).then(bookHandler);

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
        log.info("Starting Disruptor (ringSize={})",
                disruptor.getRingBuffer().getBufferSize());
        disruptor.start();
        log.info("Disruptor started");
    }

    public void shutdown() {
        log.info("Shutting down Disruptor");
        disruptor.shutdown();
        log.info("Disruptor stopped");
    }
}
