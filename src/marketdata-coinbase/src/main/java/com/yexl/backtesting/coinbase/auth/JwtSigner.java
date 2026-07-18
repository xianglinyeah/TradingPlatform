package com.yexl.backtesting.coinbase.auth;

import io.jsonwebtoken.Jwts;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.security.SecureRandom;
import java.time.Instant;
import java.util.HexFormat;

/**
 * ES256 (ECDSA P-256 SHA-256) JWT signer for Coinbase Advanced Trade
 * WebSocket authentication.
 *
 * <p>JWT cache strategy:
 * <ul>
 *   <li>JWT is signed once and cached.</li>
 *   <li>{@link #get()} returns the cached token if its remaining lifetime is
 *       greater than {@code refreshBeforeExpSeconds}; otherwise it re-signs
 *       under a synchronized block (double-checked locking).</li>
 *   <li>{@link #invalidate()} forces a refresh on the next {@link #get()} —
 *       call this when the server rejects a JWT.</li>
 * </ul>
 *
 * <p>The cache is shared across all WS subscribe/unsubscribe calls on the
 * same connection, so signing cost (~0.5 ms for ES256) is amortized over
 * {@code ttl - refreshBeforeExp} seconds.
 */
public final class JwtSigner {

    private static final Logger log = LoggerFactory.getLogger(JwtSigner.class);

    private final CdpCredentials credentials;
    private final int ttlSeconds;
    private final int refreshBeforeExpSeconds;
    private final SecureRandom random = new SecureRandom();

    private volatile String currentJwt;
    private volatile long currentJwtExpEpochSeconds;
    private final Object refreshLock = new Object();

    public JwtSigner(CdpCredentials credentials, int ttlSeconds, int refreshBeforeExpSeconds) {
        if (ttlSeconds <= refreshBeforeExpSeconds) {
            throw new IllegalArgumentException(
                    "ttlSeconds (" + ttlSeconds + ") must be > refreshBeforeExpSeconds ("
                    + refreshBeforeExpSeconds + ")");
        }
        this.credentials = credentials;
        this.ttlSeconds = ttlSeconds;
        this.refreshBeforeExpSeconds = refreshBeforeExpSeconds;
    }

    /**
     * @return a valid JWT, re-signing if the cached one is close to expiry.
     */
    public String get() {
        String jwt = currentJwt;
        if (jwt != null && !needsRefresh()) {
            return jwt;
        }
        synchronized (refreshLock) {
            if (currentJwt == null || needsRefresh()) {
                sign();
            }
            return currentJwt;
        }
    }

    public void invalidate() {
        synchronized (refreshLock) {
            currentJwt = null;
            currentJwtExpEpochSeconds = 0L;
        }
        log.info("JWT cache invalidated; next get() will re-sign");
    }

    private boolean needsRefresh() {
        long now = Instant.now().getEpochSecond();
        return (currentJwtExpEpochSeconds - now) < refreshBeforeExpSeconds;
    }

    private void sign() {
        long now = Instant.now().getEpochSecond();
        String nonce = HexFormat.of().formatHex(random.generateSeed(16));

        currentJwt = Jwts.builder()
                .header()
                    .keyId(credentials.apiKeyName())
                    .add("nonce", nonce)
                    .and()
                .issuer("cdp")
                .subject(credentials.apiKeyName())
                .claim("nbf", now)
                .claim("exp", now + ttlSeconds)
                .signWith(credentials.signingKey(), Jwts.SIG.ES256)
                .compact();
        currentJwtExpEpochSeconds = now + ttlSeconds;
        log.debug("Re-signed JWT (ttl={}s, refresh-before-exp={}s)",
                ttlSeconds, refreshBeforeExpSeconds);
    }
}
