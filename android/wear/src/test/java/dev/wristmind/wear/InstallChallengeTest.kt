package dev.wristmind.wear

import org.junit.Assert.*
import org.junit.Test

class InstallChallengeTest {
    private val nonce = "10000000-0000-4000-8000-000000000001"
    @Test fun requiresExactFreshChallengeBeforeCredentials() {
        assertTrue(InstallChallenge.accepts(nonce, nonce, 1500, 1000))
        assertFalse(InstallChallenge.accepts(null, nonce, 1500, 1000))
        assertFalse(InstallChallenge.accepts(nonce, "10000000-0000-4000-8000-000000000002", 1500, 1000))
        assertFalse(InstallChallenge.accepts(nonce, nonce, 1000, 1000))
        assertFalse(InstallChallenge.accepts(nonce, nonce, 999, 1000))
        assertFalse(InstallChallenge.accepts(nonce, nonce, 1000 + InstallChallenge.LIFETIME_MS + 1, 1000))
        assertFalse(InstallChallenge.accepts("-".repeat(36), "-".repeat(36), 1500, 1000))
    }
}
