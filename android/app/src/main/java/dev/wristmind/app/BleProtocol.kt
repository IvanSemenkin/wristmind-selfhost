package dev.wristmind.app

import java.util.UUID

object BleProtocol {
    val ADVERTISING_UUID: UUID = UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb")
    val SERVICE_UUID: UUID = UUID.fromString("8a710001-5f31-4a7c-bc51-6a7c250d6f10")
    val COMMAND_UUID: UUID = UUID.fromString("8a710002-5f31-4a7c-bc51-6a7c250d6f10")
    val EVENT_UUID: UUID = UUID.fromString("8a710003-5f31-4a7c-bc51-6a7c250d6f10")
    val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    data class Command(
        val id: String,
        val name: String,
        val chatId: Long? = null,
        val exchangeId: Long? = null,
    )

    fun parseCommand(value: ByteArray): Command? {
        val parts = value.toString(Charsets.UTF_8).trim().split('|')
        if (parts.size != 3 || parts[0] != "C") return null
        return Command(parts[1].take(8), parts[2].uppercase())
    }

    fun status(state: String): ByteArray = "S|$state".toByteArray(Charsets.UTF_8)
    fun error(code: String): ByteArray = "E|${code.take(16)}".toByteArray(Charsets.UTF_8)

    fun answerFrames(text: String): List<ByteArray> = textFrames("A", text)

    fun transcriptFrames(text: String): List<ByteArray> =
        textFrames("T", text.replace(Regex("\\s+"), " ").trim().take(180))

    private fun textFrames(type: String, text: String): List<ByteArray> {
        val clean = text.replace(Regex("\\s+"), " ").trim()
        val chunks = mutableListOf<String>()
        val current = StringBuilder()
        clean.forEach { character ->
            val candidate = current.toString() + character
            if (candidate.toByteArray(Charsets.UTF_8).size > 12 && current.isNotEmpty()) {
                chunks += current.toString()
                current.clear()
            }
            current.append(character)
        }
        if (current.isNotEmpty()) chunks += current.toString()
        val total = chunks.size.coerceAtMost(99)
        return chunks.take(total).mapIndexed { index, chunk ->
            "$type|${index + 1}|$total|$chunk".toByteArray(Charsets.UTF_8)
        }
    }
}
