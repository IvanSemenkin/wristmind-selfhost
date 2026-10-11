package dev.wristmind.phone.install

import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class AdbTunnelTest {
    @Test fun forwardsBytesUnchangedAndClosesOnPeerEof() {
        ServerSocket(0).use { server ->
            val worker = Executors.newSingleThreadExecutor()
            try {
                val peer = worker.submit {
                    server.accept().use { socket ->
                        val bytes = socket.getInputStream().readNBytes(4)
                        assertArrayEquals(byteArrayOf(0, 1, -1, 7), bytes)
                        socket.getOutputStream().write(bytes)
                    }
                }
                AdbTunnel("127.0.0.1", server.localPort).use { tunnel ->
                    Socket("127.0.0.1", tunnel.localPort).use { client ->
                        client.soTimeout = 3000
                        client.getOutputStream().write(byteArrayOf(0, 1, -1, 7))
                        assertArrayEquals(byteArrayOf(0, 1, -1, 7), client.getInputStream().readNBytes(4))
                    }
                }
                peer.get(3, TimeUnit.SECONDS)
            } finally { worker.shutdownNow() }
        }
    }
    @Test fun deadlineWakesBlockedReader() {
        ServerSocket(0).use { server ->
            val worker = Executors.newSingleThreadExecutor()
            try {
                val peer = worker.submit { server.accept().use { it.getInputStream().read() } }
                AdbTunnel("127.0.0.1", server.localPort).use { tunnel ->
                    Socket("127.0.0.1", tunnel.localPort).use { client ->
                        client.soTimeout = 3000
                        tunnel.extend(1)
                        assertEquals(-1, client.getInputStream().read())
                    }
                }
                peer.get(3, TimeUnit.SECONDS)
            } finally { worker.shutdownNow() }
        }
    }
}
