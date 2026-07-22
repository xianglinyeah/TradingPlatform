package com.yexl.trading.coinbase.auth;

import io.jsonwebtoken.Jws;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.Claims;
import org.junit.jupiter.api.Test;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.spec.ECGenParameterSpec;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;

class JwtSignerTest {

    private static CdpCredentials ephemeralCredentials(String apiKeyName) throws Exception {
        KeyPairGenerator kpg = KeyPairGenerator.getInstance("EC");
        kpg.initialize(new ECGenParameterSpec("secp256r1"));
        KeyPair kp = kpg.generateKeyPair();
        return new CdpCredentials(apiKeyName, kp.getPrivate());
    }

    @Test
    void constructorRejectsTtlNotGreaterThanRefreshWindow() throws Exception {
        CdpCredentials creds = ephemeralCredentials("organizations/org/apiKeys/key");
        assertThrows(IllegalArgumentException.class, () -> new JwtSigner(creds, 60, 60));
        assertThrows(IllegalArgumentException.class, () -> new JwtSigner(creds, 30, 60));
    }

    @Test
    void producesAValidEs256JwtSignedByTheConfiguredKey() throws Exception {
        KeyPairGenerator kpg = KeyPairGenerator.getInstance("EC");
        kpg.initialize(new ECGenParameterSpec("secp256r1"));
        KeyPair kp = kpg.generateKeyPair();
        String apiKeyName = "organizations/org123/apiKeys/key456";
        CdpCredentials creds = new CdpCredentials(apiKeyName, kp.getPrivate());
        JwtSigner signer = new JwtSigner(creds, 120, 60);

        String jwt = signer.get();

        Jws<Claims> parsed = Jwts.parser().verifyWith(kp.getPublic()).build().parseSignedClaims(jwt);
        assertEquals(apiKeyName, parsed.getHeader().get("kid"));
        assertNotNull(parsed.getHeader().get("nonce"));
        assertEquals("cdp", parsed.getPayload().getIssuer());
        assertEquals(apiKeyName, parsed.getPayload().getSubject());
    }

    @Test
    void getCachesTheTokenAcrossCalls() throws Exception {
        CdpCredentials creds = ephemeralCredentials("organizations/org/apiKeys/key");
        JwtSigner signer = new JwtSigner(creds, 120, 60);

        String first = signer.get();
        String second = signer.get();

        assertSame(first, second);
    }

    @Test
    void invalidateForcesANewTokenOnNextGet() throws Exception {
        CdpCredentials creds = ephemeralCredentials("organizations/org/apiKeys/key");
        JwtSigner signer = new JwtSigner(creds, 120, 60);

        String first = signer.get();
        signer.invalidate();
        String second = signer.get();

        assertNotEquals(first, second);
    }
}
