package com.yexl.backtesting.coinbase.auth;

import org.bouncycastle.asn1.pkcs.PrivateKeyInfo;
import org.bouncycastle.openssl.PEMKeyPair;
import org.bouncycastle.openssl.PEMParser;
import org.bouncycastle.openssl.jcajce.JcaPEMKeyConverter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.StringReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.PrivateKey;

/**
 * Coinbase Developer Platform (CDP) API credentials.
 *
 * <p>Consists of:
 * <ul>
 *   <li>{@code apiKeyName} — the CDP key name, of the form
 *       {@code organizations/{org_id}/apiKeys/{key_id}}.</li>
 *   <li>{@code signingKey} — the EC (P-256) private key used to sign JWTs.</li>
 * </ul>
 *
 * <p>Both PKCS#8 ({@code -----BEGIN PRIVATE KEY-----}) and SEC1
 * ({@code -----BEGIN EC PRIVATE KEY-----}) PEM formats are supported via
 * BouncyCastle's {@link PEMParser}.
 */
public record CdpCredentials(String apiKeyName, PrivateKey signingKey) {

    private static final Logger log = LoggerFactory.getLogger(CdpCredentials.class);

    public static CdpCredentials load(String apiKeyName, String signingKeyPemPath) {
        if (apiKeyName == null || apiKeyName.isBlank()) {
            throw new IllegalArgumentException(
                    "CDP API key name is required. Set env COINBASE_API_KEY " +
                    "or coinbase.auth.api-key in application.properties.");
        }
        if (signingKeyPemPath == null || signingKeyPemPath.isBlank()) {
            throw new IllegalArgumentException(
                    "CDP signing key PEM path is required. Set env COINBASE_SIGNING_KEY_PATH " +
                    "or coinbase.auth.signing-key-path in application.properties.");
        }
        try {
            String pem = Files.readString(Path.of(signingKeyPemPath));
            PrivateKey key = parsePem(pem);
            log.info("CDP credentials loaded: apiKey={}, keyAlg={}",
                    apiKeyName, key.getAlgorithm());
            return new CdpCredentials(apiKeyName, key);
        } catch (IOException e) {
            throw new RuntimeException(
                    "Failed to read signing key PEM: " + signingKeyPemPath, e);
        }
    }

    private static PrivateKey parsePem(String pem) {
        try (PEMParser parser = new PEMParser(new StringReader(pem))) {
            Object obj = parser.readObject();
            if (obj == null) {
                throw new RuntimeException("No PEM object found in signing key file");
            }
            PrivateKeyInfo info;
            if (obj instanceof PrivateKeyInfo pki) {
                // PKCS#8 ("-----BEGIN PRIVATE KEY-----")
                info = pki;
            } else if (obj instanceof PEMKeyPair pemKeyPair) {
                // SEC1 ("-----BEGIN EC PRIVATE KEY-----") — PEMParser hands back a
                // key pair (private + derived public), not a bare PrivateKeyInfo.
                info = pemKeyPair.getPrivateKeyInfo();
            } else {
                throw new RuntimeException(
                        "Unexpected PEM object type: " + obj.getClass().getName() +
                        " — expected a private key. If you have an encrypted PEM, " +
                        "decrypt it first with: openssl pkcs8 -topk8 -nocrypt ...");
            }
            return new JcaPEMKeyConverter().getPrivateKey(info);
        } catch (IOException e) {
            throw new RuntimeException("Failed to parse signing key PEM", e);
        }
    }
}
