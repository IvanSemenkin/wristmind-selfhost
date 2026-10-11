package dev.wristmind.wear

import java.io.ByteArrayInputStream
import java.util.Base64
import java.util.Random
import java.util.zip.InflaterInputStream
import org.junit.Assert.*
import org.junit.Test

class SpeechAudioPacketTest {
    @Test fun `speech compression preserves every PCM byte`() {
        val pcm = ByteArray(51_200) { (it % 19).toByte() }
        val packet = speechAudioPacket(pcm)
        assertEquals("pcm_zlib", packet.encoding)
        val restored = InflaterInputStream(ByteArrayInputStream(Base64.getDecoder().decode(packet.data))).readBytes()
        assertArrayEquals(pcm, restored)
        assertTrue(packet.wireBytes < pcm.size)
    }
    @Test fun `incompressible input stays raw`() {
        val pcm = ByteArray(12_800).also { Random(47).nextBytes(it) }
        val packet = speechAudioPacket(pcm)
        assertEquals("pcm", packet.encoding)
        assertArrayEquals(pcm, Base64.getDecoder().decode(packet.data))
    }
}
