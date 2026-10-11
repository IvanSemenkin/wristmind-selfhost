package dev.wristmind.phone.install

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** ADB shell v2 returns an explicit exit frame; never wait for the library's stream EOF. */
internal object ShellProtocol {
    data class Reply(val text: String, val exitCode: Int)
    fun stdin(bytes: ByteArray, size: Int): ByteArray {
        require(size in 0..4000 && size <= bytes.size)
        return ByteBuffer.allocate(size + 5).order(ByteOrder.LITTLE_ENDIAN)
            .put(0).putInt(size).put(bytes, 0, size).array()
    }
    fun closeInput(): ByteArray = byteArrayOf(4, 0, 0, 0, 0)
    fun readReply(input: InputStream): Reply {
        val output = ByteArrayOutputStream()
        while (true) {
            val header = readFully(input, 5)
            val id = header[0].toInt() and 255
            val size = ByteBuffer.wrap(header, 1, 4).order(ByteOrder.LITTLE_ENDIAN).int
            require(size in 0..1048576 && output.size() + size <= 1048576) { "Ответ часов слишком велик" }
            val bytes = readFully(input, size)
            when (id) {
                1, 2 -> output.write(bytes)
                3 -> {
                    require(size in 1..4) { "Некорректный ответ об окончании команды" }
                    var code = 0
                    bytes.forEachIndexed { index, byte -> code = code or ((byte.toInt() and 255) shl (index * 8)) }
                    return Reply(output.toByteArray().decodeToString(), code)
                }
                else -> error("Некорректный пакет ADB shell v2")
            }
        }
    }
    private fun readFully(input: InputStream, size: Int): ByteArray = ByteArray(size).also { bytes ->
        var offset = 0
        while (offset < size) {
            val read = input.read(bytes, offset, size - offset)
            if (read < 0) throw java.io.EOFException("Команда часов оборвалась до завершения")
            offset += read
        }
    }
}
