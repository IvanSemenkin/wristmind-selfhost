package dev.wristmind.wear

internal class VoiceDraftComposer(private val baseDraft: String) {
    fun merge(transcript: String): String {
        val normalizedTranscript = transcript.trim()
        if (normalizedTranscript.isEmpty()) return baseDraft
        if (baseDraft.isBlank()) return normalizedTranscript
        return if (baseDraft.last().isWhitespace()) {
            baseDraft + normalizedTranscript
        } else {
            "$baseDraft $normalizedTranscript"
        }
    }
}
