package dev.wristmind.wear

import java.io.ByteArrayOutputStream
import java.util.zip.DeflaterOutputStream
import java.util.Base64

internal data class SpeechAudioPacket(val data: String, val encoding: String, val rawBytes: Int, val wireBytes: Int)

/** Lossless compression only when it actually reduces the upload. */
internal fun speechAudioPacket(pcm: ByteArray): SpeechAudioPacket {
    val output = ByteArrayOutputStream()
    DeflaterOutputStream(output).use { it.write(pcm) }
    val compressed = output.toByteArray()
    val smaller = compressed.size < pcm.size
    val wire = if (smaller) compressed else pcm
    return SpeechAudioPacket(Base64.getEncoder().encodeToString(wire), if (smaller) "pcm_zlib" else "pcm", pcm.size, wire.size)
}
