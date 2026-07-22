package com.yexl.trading.coinbase.ws;

import com.lmax.disruptor.EventTranslatorOneArg;
import com.lmax.disruptor.RingBuffer;
import com.yexl.trading.coinbase.auth.JwtSigner;
import com.yexl.trading.coinbase.config.AppConfig;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.coinbase.recording.FrameRecorder;
import com.yexl.trading.marketdata.recovery.RecoverableConnection;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import io.netty.bootstrap.Bootstrap;
import io.netty.channel.Channel;
import io.netty.channel.ChannelFuture;
import io.netty.channel.ChannelHandlerContext;
import io.netty.channel.ChannelInitializer;
import io.netty.channel.ChannelOption;
import io.netty.channel.ChannelPipeline;
import io.netty.channel.SimpleChannelInboundHandler;
import io.netty.channel.nio.NioEventLoopGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioSocketChannel;
import io.netty.handler.codec.http.DefaultHttpHeaders;
import io.netty.handler.codec.http.FullHttpResponse;
import io.netty.handler.codec.http.HttpClientCodec;
import io.netty.handler.codec.http.HttpObjectAggregator;
import io.netty.handler.codec.http.websocketx.CloseWebSocketFrame;
import io.netty.handler.codec.http.websocketx.PongWebSocketFrame;
import io.netty.handler.codec.http.websocketx.TextWebSocketFrame;
import io.netty.handler.codec.http.websocketx.WebSocketClientHandshaker;
import io.netty.handler.codec.http.websocketx.WebSocketClientHandshakerFactory;
import io.netty.handler.codec.http.websocketx.WebSocketVersion;
import io.netty.handler.proxy.HttpProxyHandler;
import io.netty.handler.proxy.ProxyHandler;
import io.netty.handler.proxy.Socks5ProxyHandler;
import io.netty.handler.ssl.SslContext;
import io.netty.handler.ssl.SslContextBuilder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.URI;
import java.util.List;
import java.util.concurrent.CountDownLatch;

/**
 * Thread 1 — Netty WebSocket client for Coinbase Advanced Trade.
 *
 * <p>Responsibilities:
 * <ul>
 *   <li>Establish the WSS handshake to {@code wss://advanced-trade-ws.coinbase.com}.</li>
 *   <li>Subscribe to {@code level2} (per product) and {@code heartbeats}
 *       after handshake. JWT attached per Coinbase requirements.</li>
 *   <li>For every inbound text frame, copy the payload into a Disruptor event
 *       via {@link RingBuffer#tryPublishEvent(EventTranslatorOneArg, Object)}.
 *       No parsing happens on this thread.</li>
 *   <li>Ring-buffer-full = data loss; logged, not yet recovered (a full ring
 *       buffer indicates the pipeline itself is backed up, not a connection
 *       fault — reconnecting wouldn't help).</li>
 * </ul>
 *
 * <p>Implements {@link RecoverableConnection} so {@link RecoveryManager} can
 * drive reconnect-with-backoff and standalone resubscribe from its own
 * dedicated thread. {@link #reconnect()} and {@link #resubscribeLevel2}
 * are the only entry points the recovery thread calls; both are safe to
 * invoke repeatedly and never run concurrently with each other because
 * {@code RecoveryManager} serializes all recovery work on a single thread.
 */
public final class CoinbaseWsClient implements RecoverableConnection {

    private static final Logger log = LoggerFactory.getLogger(CoinbaseWsClient.class);

    private static final EventTranslatorOneArg<MarketDataEvent, String> PUBLISH_TRANSLATOR =
            (event, sequence, payload) -> {
                event.reset();
                event.rawJson = payload;
                // Both clock domains stamped back-to-back: nanoTime for
                // monotonic in-process latency segments, epoch nanos so the
                // exchange's wall-clock timestamp has something comparable.
                event.receiveTimeNanos = System.nanoTime();
                java.time.Instant now = java.time.Instant.now();
                event.receiveTimeEpochNanos = now.getEpochSecond() * 1_000_000_000L + now.getNano();
            };

    private final AppConfig config;
    private final JwtSigner jwtSigner;
    private final RingBuffer<MarketDataEvent> ringBuffer;
    private final RecoveryManager recoveryManager;
    /** Optional raw-frame recorder; null when recording is disabled. */
    private final FrameRecorder frameRecorder;

    private NioEventLoopGroup group;
    private volatile Channel channel;

    /**
     * Counts down only on an intentional {@link #stop()} — never on an
     * individual channel drop, since {@link RecoveryManager} may replace
     * {@link #channel} many times over the process lifetime via
     * {@link #reconnect()}. {@link #awaitClose()} must track the client's
     * lifecycle, not any one channel's.
     */
    private final CountDownLatch stopped = new CountDownLatch(1);

    public CoinbaseWsClient(AppConfig config, JwtSigner jwtSigner,
                            RingBuffer<MarketDataEvent> ringBuffer, RecoveryManager recoveryManager,
                            FrameRecorder frameRecorder) {
        this.config = config;
        this.jwtSigner = jwtSigner;
        this.ringBuffer = ringBuffer;
        this.recoveryManager = recoveryManager;
        this.frameRecorder = frameRecorder;
    }

    /** Initial connect, called once from {@code Main} at startup. Fails fast on error. */
    public void start() throws Exception {
        this.group = new NioEventLoopGroup(1, r -> {
            Thread t = new Thread(r, "coinbase-ws-io");
            t.setDaemon(true);
            return t;
        });
        connectOnce();
    }

    /**
     * {@inheritDoc}
     *
     * <p>Closes the current channel (if any) and re-establishes it on the
     * same {@link NioEventLoopGroup}. Blocking — intended to run only on
     * {@link RecoveryManager}'s dedicated recovery thread.
     */
    @Override
    public void reconnect() throws Exception {
        Channel old = this.channel;
        if (old != null && old.isOpen()) {
            old.close().awaitUninterruptibly();
        }
        connectOnce();
    }

    private void connectOnce() throws Exception {
        URI uri = new URI(config.wsUrl);
        String scheme = uri.getScheme();
        if (!"wss".equalsIgnoreCase(scheme) && !"ws".equalsIgnoreCase(scheme)) {
            throw new IllegalArgumentException("Unsupported scheme: " + scheme);
        }
        boolean ssl = "wss".equalsIgnoreCase(scheme);
        int port = uri.getPort() > 0 ? uri.getPort() : (ssl ? 443 : 80);
        String host = uri.getHost();

        SslContext sslContext = ssl ? SslContextBuilder.forClient().build() : null;

        // Subprotocol = null, allowExtensions = true — maxFramePayloadLength is
        // config.wsMaxFrameBytes (large snapshots can exceed the default 64KB).
        WebSocketClientHandshaker handshaker = WebSocketClientHandshakerFactory.newHandshaker(
                uri,
                WebSocketVersion.V13,
                /* subprotocol */ null,
                /* allowExtensions */ true,
                new DefaultHttpHeaders(),
                /* maxFramePayloadLength */ config.wsMaxFrameBytes
        );

        Bootstrap bootstrap = new Bootstrap();
        bootstrap.group(group)
                .channel(NioSocketChannel.class)
                .option(ChannelOption.TCP_NODELAY, true)
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 10_000)
                .handler(new ChannelInitializer<SocketChannel>() {
                    @Override
                    protected void initChannel(SocketChannel ch) throws Exception {
                        ChannelPipeline p = ch.pipeline();
                        if (config.proxyEnabled) {
                            // Must be first: defers channelActive (and everything after
                            // it) until the proxy handshake/CONNECT tunnel completes.
                            p.addLast(newProxyHandler());
                        }
                        if (sslContext != null) {
                            p.addLast(sslContext.newHandler(ch.alloc(), host, port));
                        }
                        p.addLast(new HttpClientCodec());
                        p.addLast(new HttpObjectAggregator(config.wsMaxFrameBytes));
                        p.addLast(new WsHandler(handshaker, jwtSigner, config.productIds, ringBuffer,
                                recoveryManager, frameRecorder));
                    }
                });

        if (config.proxyEnabled) {
            log.info("Outbound proxy enabled: {}://{}:{}", config.proxyType, config.proxyHost, config.proxyPort);
        }
        log.info("Connecting to {} (host={}, port={})", config.wsUrl, host, port);
        ChannelFuture cf = bootstrap.connect(host, port).sync();
        this.channel = cf.channel();
    }

    /**
     * A fresh {@link ProxyHandler} for the outbound TCP connection — the local
     * SOCKS5/HTTP proxy address (e.g. v2rayN) that the actual WSS connection to
     * Coinbase tunnels through. Must be created per-channel; {@link ProxyHandler}
     * instances are single-use.
     */
    private ProxyHandler newProxyHandler() {
        InetSocketAddress proxyAddr = new InetSocketAddress(config.proxyHost, config.proxyPort);
        return switch (config.proxyType) {
            case "socks5" -> new Socks5ProxyHandler(proxyAddr);
            case "http" -> new HttpProxyHandler(proxyAddr);
            default -> throw new IllegalArgumentException("Unknown proxy type: " + config.proxyType);
        };
    }

    /**
     * {@inheritDoc}
     *
     * <p>Sends a fresh {@code level2} subscribe on the current channel without
     * reconnecting. No-op (with a warning) if there is no active channel —
     * that case is left to the reconnect path, which resubscribes everything.
     */
    @Override
    public void resubscribeLevel2(List<String> productIds) {
        Channel ch = this.channel;
        if (ch == null || !ch.isActive()) {
            log.warn("resubscribeLevel2 skipped — no active channel (products={})", productIds);
            return;
        }
        String jwt = jwtSigner.get();
        String l2Sub = new SubscriptionMessage("subscribe", "level2", productIds, jwt).toJson();
        ch.writeAndFlush(new TextWebSocketFrame(l2Sub));
        log.info("Resubscribed level2 (products={})", productIds);
    }

    /** Blocks until {@link #stop()} is called — NOT until any single channel closes, since reconnects replace it. */
    public void awaitClose() throws InterruptedException {
        stopped.await();
    }

    /** Final shutdown — call {@code RecoveryManager.shutdown()} first so a spurious channelInactive doesn't trigger a reconnect. */
    public void stop() {
        Channel ch = this.channel;
        if (ch != null) {
            ch.close().awaitUninterruptibly();
        }
        if (group != null) {
            group.shutdownGracefully();
        }
        stopped.countDown();
        log.info("WS client stopped");
    }

    static final class WsHandler extends SimpleChannelInboundHandler<Object> {

        private static final Logger log = LoggerFactory.getLogger(WsHandler.class);

        private final WebSocketClientHandshaker handshaker;
        private final JwtSigner jwtSigner;
        private final List<String> productIds;
        private final RingBuffer<MarketDataEvent> ringBuffer;
        private final RecoveryManager recoveryManager;
        private final FrameRecorder frameRecorder;

        WsHandler(WebSocketClientHandshaker handshaker, JwtSigner jwtSigner,
                  List<String> productIds, RingBuffer<MarketDataEvent> ringBuffer,
                  RecoveryManager recoveryManager, FrameRecorder frameRecorder) {
            this.handshaker = handshaker;
            this.jwtSigner = jwtSigner;
            this.productIds = productIds;
            this.ringBuffer = ringBuffer;
            this.recoveryManager = recoveryManager;
            this.frameRecorder = frameRecorder;
        }

        @Override
        public void channelActive(ChannelHandlerContext ctx) throws Exception {
            log.debug("channelActive — starting WS handshake");
            handshaker.handshake(ctx.channel());
        }

        @Override
        protected void channelRead0(ChannelHandlerContext ctx, Object msg) throws Exception {
            if (!handshaker.isHandshakeComplete()) {
                handshaker.finishHandshake(ctx.channel(), (FullHttpResponse) msg);
                log.info("WebSocket handshake complete: remote={}", ctx.channel().remoteAddress());
                recoveryManager.onChannelActive();
                sendSubscriptions(ctx.channel());
                return;
            }

            if (msg instanceof TextWebSocketFrame textFrame) {
                String payload = textFrame.text();
                publishToRingBuffer(payload);
                if (frameRecorder != null) {
                    // After publish — recording must never delay the hot path.
                    frameRecorder.offer(payload);
                }
            } else if (msg instanceof PongWebSocketFrame) {
                log.trace("Received pong");
            } else if (msg instanceof CloseWebSocketFrame closeFrame) {
                log.warn("Received WebSocket close frame: code={} reason={}",
                        closeFrame.statusCode(), closeFrame.reasonText());
                ctx.close();
            } else {
                log.debug("Ignored frame type: {}", msg.getClass().getSimpleName());
            }
        }

        private void publishToRingBuffer(String json) {
            boolean published = ringBuffer.tryPublishEvent(PUBLISH_TRANSLATOR, json);
            if (!published) {
                // A full ring buffer means the pipeline is backed up, not that the
                // connection is broken — reconnecting wouldn't help, so this is
                // logged only, not routed through RecoveryManager.
                log.error("RingBuffer FULL — WS frame dropped ({} chars). Book may now be corrupt.",
                        json.length());
            }
        }

        private void sendSubscriptions(Channel ch) {
            // JWTs are deliberately not logged (even at DEBUG) — each is a live,
            // usable credential for the remainder of its TTL, and this fires on
            // every reconnect.
            String jwt = jwtSigner.get();

            String l2Sub = new SubscriptionMessage("subscribe", "level2", productIds, jwt).toJson();
            ch.writeAndFlush(new TextWebSocketFrame(l2Sub));
            log.info("Sent level2 subscribe (products={})", productIds);

            // heartbeats channel must be subscribed to keep the connection
            // alive — otherwise Coinbase closes idle channels after 60-90s.
            String hbSub = new SubscriptionMessage("subscribe", "heartbeats", null, jwt).toJson();
            ch.writeAndFlush(new TextWebSocketFrame(hbSub));
            log.info("Sent heartbeats subscribe");
        }

        @Override
        public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
            log.error("WS channel exception", cause);
            // ctx.close() completing fires channelInactive below, which is
            // where recovery is triggered — don't trigger it twice here.
            ctx.close();
        }

        @Override
        public void channelInactive(ChannelHandlerContext ctx) {
            log.warn("WS channel became inactive (remote={}); handing off to RecoveryManager",
                    ctx.channel().remoteAddress());
            recoveryManager.onChannelInactive();
        }
    }
}
