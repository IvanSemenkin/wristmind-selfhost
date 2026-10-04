package dev.wristmind.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class ProxyProtocolTest {
    @Test
    fun modeWatchVisibilitySurvivesProxySerialization() {
        val hidden = Mode("mode", "География", "#4CAF73", "spark", "", "deepseek:deepseek-flash", true)

        assertTrue(ProxyJson.parseModes(ProxyJson.modes(listOf(hidden))).single().hiddenOnWatch)
    }

    @Test
    fun reassemblesOutOfOrderPartsAndAcceptsIdenticalDuplicate() {
        val payload = ByteArray(ProxyProtocol.MAX_PART_BYTES * 2 + 17) { (it % 251).toByte() }
        val parts = ProxyChunker.split(UUID.randomUUID().toString(), "messages", payload)
        val assembler = ProxyAssembler()

        assertTrue(assembler.accept(parts[1]) is ProxyAssemblyResult.Incomplete)
        assertTrue(assembler.accept(parts[1]) is ProxyAssemblyResult.Incomplete)
        assertTrue(assembler.accept(parts[0]) is ProxyAssemblyResult.Incomplete)
        val result = assembler.accept(parts[2]) as ProxyAssemblyResult.Complete

        assertArrayEquals(payload, result.payload)
    }

    @Test
    fun rejectsConflictingDuplicate() {
        val parts = ProxyChunker.split("request", "messages", ByteArray(ProxyProtocol.MAX_PART_BYTES + 1) { 7 })
        val assembler = ProxyAssembler()
        assembler.accept(parts[0])
        val conflict = parts[0].copy(payloadBase64 = parts[1].payloadBase64)

        assertEquals(
            ProxyProtocol.ERROR_PART_CONFLICT,
            (assembler.accept(conflict) as ProxyAssemblyResult.Rejected).errorCode,
        )
    }

    @Test
    fun reportsMissingPartBeforeCompletion() {
        val parts = ProxyChunker.split("missing", "messages", ByteArray(ProxyProtocol.MAX_PART_BYTES * 2 + 1))
        val result = ProxyAssembler().accept(parts.last()) as ProxyAssemblyResult.Incomplete

        assertEquals(listOf(0, 1), result.missingParts)
    }

    @Test
    fun rejectsWrongChecksum() {
        val part = ProxyChunker.split("checksum", "health", "hello".toByteArray()).single()
            .copy(checksumSha256 = "0".repeat(64))

        assertEquals(
            ProxyProtocol.ERROR_CHECKSUM,
            (ProxyAssembler().accept(part) as ProxyAssemblyResult.Rejected).errorCode,
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsPayloadAboveLimit() {
        ProxyChunker.split("large", "messages", ByteArray(ProxyProtocol.MAX_PAYLOAD_BYTES + 1))
    }

    @Test
    fun expiresIncompleteAssembly() {
        var now = 100L
        val parts = ProxyChunker.split("timeout", "messages", ByteArray(ProxyProtocol.MAX_PART_BYTES + 1))
        val assembler = ProxyAssembler { now }
        assembler.accept(parts[0])
        now += ProxyProtocol.ASSEMBLY_TIMEOUT_MS + 1

        assertEquals(
            ProxyProtocol.ERROR_ASSEMBLY_TIMEOUT,
            (assembler.accept(parts[1]) as ProxyAssemblyResult.Rejected).errorCode,
        )
    }

    @Test
    fun envelopeRoundTripIncludesResponseFields() {
        val original = ProxyChunker.split(
            requestId = "round-trip",
            operation = "health",
            payload = "ok".toByteArray(),
            status = ProxyProtocol.STATUS_OK,
            httpStatus = 200,
            retryable = false,
        ).single()

        assertEquals(original, ProxyEnvelope.fromByteArray(original.toByteArray()))
    }

    @Test
    fun outgoingPartsExpireAfterFiveMinutes() {
        var now = 0L
        val cache = ProxyOutgoingCache { now }
        val part = ProxyChunker.split("cached", "messages", "value".toByteArray()).single()
        cache.put("cached", listOf(part))
        assertEquals(part, cache.get("cached", 0))
        now += ProxyProtocol.OUTGOING_CACHE_MS + 1
        assertNull(cache.get("cached", 0))
    }
}
