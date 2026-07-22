package com.yexl.trading.okx.ws;

import com.lmax.disruptor.EventTranslatorOneArg;
import com.lmax.disruptor.RingBuffer;
import com.yexl.trading.marketdata.model.MarketDataEvent;
import com.yexl.trading.marketdata.recovery.RecoverableConnection;
import com.yexl.trading.marketdata.recovery.RecoveryManager;
import com.yexl.trading.okx.config.AppConfig;
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
import io.netty.util.concurrent.ScheduledFuture;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.URI;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Thread 1 — Netty WebSocket client for the OKX v5 public endpoint.
 *
 * <p>Differences from the Coinbase client, all protocol-driven:
 * <ul>
 *   <li>No auth: the public {@code books} channel is unauthenticated.</li>
 *   <li>Liveness is client-driven: OKX has no server-push heartbeat channel;
 *       instead this client sends a literal {@code "ping"} text frame on a
 *       fixed schedule (on the I/O event loop) and the server answers
 *       {@code "pong"}, which the parser maps to a HEARTBEAT event feeding
 *       the same {@link RecoveryManager} watchdog.</li>
 *   <li>{@link #resubscribeLevel2} must unsubscribe first: OKX rejects a
 *       duplicate subscribe on a live subscription, and only a fresh
 *       subscribe re-delivers the 400-level snapshot needed to revive a
 *       STALE book.</li>
 * </ul>
 */
public final class OkxWsClient implements RecoverableConnection {

    private static final Logger log = LoggerFactory.getLogger(OkxWsClient.class);

    private static final EventTranslatorOneArg<MarketDataEvent, String> PUBLISH_TRANSLATOR =
            (event, sequence, payload) -> {
                event.reset();
                event.rawJson = payload;
                event.receiveTimeNanos = System.nanoTime();
                java.time.Instant now = java.time.Instant.now();
                event.receiveTimeEpochNanos = now.getEpochSecond() * 1_000_000_000L + now.getNano();
            };

    private final AppConfig config;
    private final RingBuffer<MarketDataEvent> ringBuffer;
    private final RecoveryManager recoveryManager;

    private NioEventLoopGroup group;
    private volatile Channel channel;

    /** Counts down only on intentional {@link #stop()} — reconnects replace {@link #channel} freely. */
    private final CountDownLatch stopped = new CountDownLatch(1);

    public OkxWsClient(AppConfig config, RingBuffer<MarketDataEvent> ringBuffer,
                       RecoveryManager recoveryManager) {
        this.config = config;
        this.ringBuffer = ringBuffer;
        this.recoveryManager = recoveryManager;
    }

    public void start() throws Exception {
        this.group = new NioEventLoopGroup(1, r -> {
            Thread t = new Thread(r, "okx-ws-io");
            t.setDaemon(true);
            return t;
        });
        connectOnce();
    }

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

        WebSocketClientHandshaker handshaker = WebSocketClientHandshakerFactory.newHandshaker(
                uri, WebSocketVersion.V13, null, true,
                new DefaultHttpHeaders(), config.wsMaxFrameBytes);

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
                            p.addLast(newProxyHandler());
                        }
                        if (sslContext != null) {
                            p.addLast(sslContext.newHandler(ch.alloc(), host, port));
                        }
                        p.addLast(new HttpClientCodec());
                        p.addLast(new HttpObjectAggregator(config.wsMaxFrameBytes));
                        p.addLast(new WsHandler(handshaker, config.productIds, config.pingIntervalMs,
                                ringBuffer, recoveryManager));
                    }
                });

        if (config.proxyEnabled) {
            log.info("Outbound proxy enabled: {}://{}:{}", config.proxyType, config.proxyHost, config.proxyPort);
        }
        log.info("Connecting to {} (host={}, port={})", config.wsUrl, host, port);
        ChannelFuture cf = bootstrap.connect(host, port).sync();
        this.channel = cf.channel();
    }

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
     * <p>Unsubscribe-then-subscribe on the live channel: OKX only sends the
     * fresh snapshot on a new subscription, and errors on a duplicate one.
     * The server processes the two ops in order on the connection.
     */
    @Override
    public void resubscribeLevel2(List<String> productIds) {
        Channel ch = this.channel;
        if (ch == null || !ch.isActive()) {
            log.warn("resubscribe skipped — no active channel (instIds={})", productIds);
            return;
        }
        ch.writeAndFlush(new TextWebSocketFrame(
                new OkxSubscription("unsubscribe", "books", productIds).toJson()));
        ch.writeAndFlush(new TextWebSocketFrame(
                new OkxSubscription("subscribe", "books", productIds).toJson()));
        log.info("Resubscribed books (instIds={})", productIds);
    }

    public void awaitClose() throws InterruptedException {
        stopped.await();
    }

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
        private final List<String> instIds;
        private final long pingIntervalMs;
        private final RingBuffer<MarketDataEvent> ringBuffer;
        private final RecoveryManager recoveryManager;

        /** Periodic "ping" sender on this channel's event loop; cancelled on close. */
        private ScheduledFuture<?> pingTask;

        WsHandler(WebSocketClientHandshaker handshaker, List<String> instIds, long pingIntervalMs,
                  RingBuffer<MarketDataEvent> ringBuffer, RecoveryManager recoveryManager) {
            this.handshaker = handshaker;
            this.instIds = instIds;
            this.pingIntervalMs = pingIntervalMs;
            this.ringBuffer = ringBuffer;
            this.recoveryManager = recoveryManager;
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
                startPing(ctx);
                return;
            }

            if (msg instanceof TextWebSocketFrame textFrame) {
                publishToRingBuffer(textFrame.text());
            } else if (msg instanceof PongWebSocketFrame) {
                log.trace("Received protocol-level pong");
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
                log.error("RingBuffer FULL — WS frame dropped ({} chars). Book may now be corrupt.",
                        json.length());
            }
        }

        private void sendSubscriptions(Channel ch) {
            String sub = new OkxSubscription("subscribe", "books", instIds).toJson();
            ch.writeAndFlush(new TextWebSocketFrame(sub));
            log.info("Sent books subscribe (instIds={})", instIds);
        }

        private void startPing(ChannelHandlerContext ctx) {
            pingTask = ctx.channel().eventLoop().scheduleAtFixedRate(
                    () -> {
                        if (ctx.channel().isActive()) {
                            ctx.channel().writeAndFlush(new TextWebSocketFrame("ping"));
                        }
                    },
                    pingIntervalMs, pingIntervalMs, TimeUnit.MILLISECONDS);
            log.info("Ping scheduler started (interval={}ms)", pingIntervalMs);
        }

        @Override
        public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
            log.error("WS channel exception", cause);
            ctx.close();
        }

        @Override
        public void channelInactive(ChannelHandlerContext ctx) {
            if (pingTask != null) {
                pingTask.cancel(false);
            }
            log.warn("WS channel became inactive (remote={}); handing off to RecoveryManager",
                    ctx.channel().remoteAddress());
            recoveryManager.onChannelInactive();
        }
    }
}
