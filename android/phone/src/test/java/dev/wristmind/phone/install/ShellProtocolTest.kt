package dev.wristmind.phone.install

import java.io.ByteArrayInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class ShellProtocolTest {
    private fun frame(id: Byte, bytes: ByteArray) = ByteBuffer.allocate(bytes.size+5)
        .order(ByteOrder.LITTLE_ENDIAN).put(id).putInt(bytes.size).put(bytes).array()
    @Test fun stopsAtExitWithoutWaitingForEof() {
        val packets = frame(1, "Success\n".toByteArray()) + frame(3, byteArrayOf(0))
        val input = object : ByteArrayInputStream(packets) {
            override fun read(b: ByteArray, off: Int, len: Int): Int {
                check(available() > 0) { "Must not read after exit" }
                return super.read(b, off, minOf(2, len)) // fragmented network frames
            }
        }
        assertEquals(ShellProtocol.Reply("Success\n",0), ShellProtocol.readReply(input))
    }
    @Test fun preservesStderrAndFailureStatus() {
        val packets=frame(2, "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]".toByteArray()) + frame(3,byteArrayOf(1,0,0,0))
        val reply=ShellProtocol.readReply(packets.inputStream())
        assertEquals(1,reply.exitCode)
        assertTrue(reply.text.contains("UPDATE_INCOMPATIBLE"))
    }
    @Test fun refusesMalformedOrTruncatedFrames() {
        listOf(byteArrayOf(1), frame(5,byteArrayOf(0)),frame(3,byteArrayOf()),
            byteArrayOf(1,-1,-1,-1,-1)).forEach {
            assertThrows(Exception::class.java) { ShellProtocol.readReply(it.inputStream()) }
        }
    }
    @Test fun encodesBoundedStdinAndExplicitClose() {
        assertArrayEquals(byteArrayOf(0,2,0,0,0,9,8),ShellProtocol.stdin(byteArrayOf(9,8),2))
        assertArrayEquals(byteArrayOf(4,0,0,0,0),ShellProtocol.closeInput())
        assertThrows(IllegalArgumentException::class.java) { ShellProtocol.stdin(ByteArray(4096),4096) }
    }
}
