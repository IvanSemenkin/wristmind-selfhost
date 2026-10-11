package dev.wristmind.phone.install

import java.io.Closeable
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/** Bounds library TCP/TLS operations, including pairing (which has no socket timeout API).
 * The loopback relay transports encrypted ADB packets unchanged; no keys are inspected here.
 */
internal class AdbTunnel(host: String, port: Int) : Closeable {
    private val remote = Socket()
    private val listener = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
    private val workers = Executors.newScheduledThreadPool(3) { task -> Thread(task, "wristmind-adb").apply { isDaemon = true } }
    @Volatile private var local: Socket? = null
    @Volatile private var closed = false
    private var deadline: ScheduledFuture<*>? = null
    val localPort: Int get() = listener.localPort
    init {
        try {
            remote.connect(InetSocketAddress(host, port), 5000)
            extend(45)
            workers.execute {
                try {
                    val socket = listener.accept()
                    local = socket
                    if (closed) { socket.close(); return@execute }
                    workers.execute { relay(socket, remote) }
                    relay(remote, socket)
                } catch (_: Exception) { close() }
            }
        } catch (error: Exception) { close(); throw IllegalStateException(
            "Часы не ответили. Проверьте общую Wi-Fi сеть, включение отладки и текущий порт.", error) }
    }
    fun extend(seconds: Long) {
        deadline?.cancel(false)
        deadline = workers.schedule({ close() }, seconds, TimeUnit.SECONDS)
    }
    private fun relay(from: Socket, to: Socket) {
        try {
            val buffer = ByteArray(16384)
            val input = from.getInputStream()
            val output = to.getOutputStream()
            while (!closed) {
                val size = input.read(buffer)
                if (size < 0) break
                output.write(buffer, 0, size); output.flush()
            }
        } catch (_: Exception) { /* Socket closure wakes both directions. */ }
        finally { close() }
    }
    override fun close() {
        closed = true
        runCatching { listener.close() }; runCatching { local?.close() }; runCatching { remote.close() }
        workers.shutdownNow()
    }
}
