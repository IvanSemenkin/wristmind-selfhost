package dev.wristmind.wear

import dev.wristmind.core.Chat
import dev.wristmind.core.ChatMessage
import dev.wristmind.core.ChatSourceCandidate
import dev.wristmind.core.DeviceToken
import dev.wristmind.core.FallbackTicket
import dev.wristmind.core.Job
import dev.wristmind.core.Mode
import dev.wristmind.core.ServerEvent
import dev.wristmind.core.WristMindApiException
import java.io.IOException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FailoverWearGatewayTest {
    @Test
    fun transportFailureFallsBackOnceAndKeepsRequestId() = runTest {
        val direct = FakeGateway(sendError = IOException("TLS"))
        val proxy = FakeProxyGateway()
        val routes = mutableListOf<Pair<Boolean, Boolean>>()
        val gateway = FailoverWearGateway(
            direct,
            proxy,
            onRoute = { usingProxy, phone -> routes += usingProxy to phone },
            sendLogger = {},
        )

        gateway.sendMessage("chat", "stable-request", "text", true, true, true)

        assertEquals(1, direct.sendCalls)
        assertEquals(1, proxy.sendCalls)
        assertEquals("stable-request", proxy.lastRequestId)
        assertTrue(proxy.lastWebSearch == true)
        assertTrue(proxy.lastResearchMode == true)
        assertEquals(true to true, routes.last())
    }

    @Test
    fun successfulDirectSendDoesNotProbePhoneBeforeReturningJob() = runTest {
        val proxy = FakeProxyGateway().apply { reachableDelayMs = 10_000L }
        val routes = mutableListOf<Pair<Boolean, Boolean>>()
        val gateway = FailoverWearGateway(FakeGateway(), proxy, onRoute = { usingProxy, phone ->
            routes += usingProxy to phone
        }, sendLogger = {})

        assertEquals("job", gateway.sendMessage("chat", "request", "text", false).id)
        assertEquals(0, proxy.isReachableCalls)
        assertEquals(false to false, routes.last())
    }

    @Test
    fun httpFailureNeverSwitchesToProxy() = runTest {
        val direct = FakeGateway(sendError = WristMindApiException(503, "server"))
        val proxy = FakeProxyGateway()
        val gateway = FailoverWearGateway(direct, proxy, sendLogger = {})

        runCatching { gateway.sendMessage("chat", "request", "text", false) }

        assertEquals(1, direct.sendCalls)
        assertEquals(0, proxy.sendCalls)
    }

    @Test
    fun healthyDirectRouteRemainsPreferredWhenPhoneIsReachable() = runTest {
        val routes = mutableListOf<Pair<Boolean, Boolean>>()
        val gateway = FailoverWearGateway(FakeGateway(), FakeProxyGateway()) { proxy, phone -> routes += proxy to phone }

        assertTrue(gateway.health())
        assertFalse(routes.last().first)
        assertTrue(routes.last().second)
    }

    @Test
    fun quickChatUsesDedicatedQuickChatOperation() = runTest {
        val direct = FakeGateway()
        val gateway = FailoverWearGateway(direct, FakeProxyGateway(), sendLogger = {})

        val chat = gateway.createQuickChat("stable-create-request")

        assertEquals("quick", chat.id)
        assertEquals(1, direct.quickChatCalls)
        assertEquals(0, direct.createChatCalls)
        assertEquals("stable-create-request", direct.lastCreateRequestId)
    }

    @Test
    fun createChatFallbackKeepsRequestId() = runTest {
        val direct = FakeGateway(createError = IOException("TLS"))
        val proxy = FakeProxyGateway()
        val gateway = FailoverWearGateway(direct, proxy, sendLogger = {})

        gateway.createChat("mode", "stable-create-request")

        assertEquals("stable-create-request", direct.lastCreateRequestId)
        assertEquals("stable-create-request", proxy.lastCreateRequestId)
    }

    /**
     * Regression: `getCapability(...).await()` has no timeout, and one hanging
     * probe used to stall a whole refresh. A hanging phone must not delay a
     * healthy direct call, and the unanswered probe is reported as "no phone".
     */
    @Test
    fun aHangingPhoneProbeIsCappedAndReportedAsUnreachable() = runTest {
        val routes = mutableListOf<Pair<Boolean, Boolean>>()
        val proxy = FakeProxyGateway().apply { reachableDelayMs = 10_000L }
        val gateway = FailoverWearGateway(FakeGateway(), proxy) { usingProxy, phone ->
            routes += usingProxy to phone
        }

        assertTrue(gateway.health())

        assertEquals(false to false, routes.last())
        assertEquals(1, proxy.isReachableCalls)
    }

    /** One probe per TTL: a refresh issues several requests and must not re-ask. */
    @Test
    fun phoneReachabilityIsProbedOncePerRefresh() = runTest {
        val proxy = FakeProxyGateway()
        val gateway = FailoverWearGateway(FakeGateway(), proxy, sendLogger = {})

        gateway.health()
        gateway.modes()
        gateway.chats()

        assertEquals(1, proxy.isReachableCalls)
    }

    /** A real transport failure still re-checks the phone before using the proxy. */
    @Test
    fun aFailedDirectCallReProbesThePhone() = runTest {
        val proxy = FakeProxyGateway()
        val gateway = FailoverWearGateway(FakeGateway(), proxy, sendLogger = {})
        gateway.health()

        val failing = FailoverWearGateway(FakeGateway(createError = IOException("TLS")), proxy, sendLogger = {})
        failing.createChat("mode", "request")

        assertTrue(proxy.isReachableCalls >= 2)
    }
}

private open class FakeGateway(
    private val sendError: Throwable? = null,
    private val createError: Throwable? = null,
) : WearGateway {
    var sendCalls = 0
    var lastRequestId: String? = null
    var lastWebSearch: Boolean? = null
    var lastResearchMode: Boolean? = null
    var quickChatCalls = 0
    var createChatCalls = 0
    var lastCreateRequestId: String? = null
    override suspend fun health() = true
    override suspend fun enroll(code: String) = DeviceToken("watch", "token", false)
    override suspend fun registerPushToken(token: String) = Unit
    override suspend fun fallbackTicket() = FallbackTicket("ticket", "2099-01-01T00:00:00Z")
    override suspend fun modes(): List<Mode> = emptyList()
    override suspend fun chats(): List<Chat> = emptyList()
    override suspend fun createChat(modeId: String, clientRequestId: String): Chat {
        createChatCalls += 1
        lastCreateRequestId = clientRequestId
        createError?.let { throw it }
        return Chat("chat", modeId, "Mode", false, "Chat")
    }
    override suspend fun createQuickChat(clientRequestId: String): Chat {
        quickChatCalls += 1
        lastCreateRequestId = clientRequestId
        createError?.let { throw it }
        return Chat("quick", "quick", "Quick", false, "Quick")
    }
    override suspend fun deleteChat(chatId: String) = Unit
    override suspend fun messages(chatId: String): List<ChatMessage> = emptyList()
    override suspend fun sendMessage(chatId: String, requestId: String, text: String, webSearch: Boolean, webResearch: Boolean, researchMode: Boolean): Job {
        sendCalls += 1
        lastRequestId = requestId
        lastWebSearch = webSearch
        lastResearchMode = researchMode
        sendError?.let { throw it }
        return Job("job", "queued")
    }
    override suspend fun syncFallbackMessage(chatId: String, requestId: String, userText: String, assistantText: String) = "synced"
    override suspend fun job(jobId: String) = Job(jobId, "complete")
    override suspend fun cancelJob(jobId: String) = Job(jobId, "cancelled")
    override suspend fun chatSourceCandidates(chatId: String): List<ChatSourceCandidate> = emptyList()
    override suspend fun saveChatSourceCandidate(chatId: String, candidateId: String, requestId: String) =
        Job("source-job", "queued")
    override suspend fun dismissChatSourceCandidate(chatId: String, candidateId: String) = Unit
    override fun events(jobId: String, after: Long): Flow<ServerEvent> = emptyFlow()
}

private class FakeProxyGateway : FakeGateway(), ProxyWearGateway {
    var isReachableCalls = 0
    var reachableDelayMs = 0L

    override suspend fun isReachable(): Boolean {
        isReachableCalls += 1
        if (reachableDelayMs > 0) delay(reachableDelayMs)
        return true
    }
}
