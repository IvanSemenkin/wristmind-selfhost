package dev.wristmind.core

import org.json.JSONArray
import org.json.JSONObject

object ProxyJson {
    fun objectBytes(builder: JSONObject.() -> Unit = {}): ByteArray =
        JSONObject().apply(builder).toString().toByteArray(Charsets.UTF_8)

    fun objectFrom(bytes: ByteArray): JSONObject = JSONObject(bytes.toString(Charsets.UTF_8))

    fun deviceToken(value: DeviceToken): ByteArray = objectBytes {
        put("device_id", value.deviceId)
        put("token", value.token)
        put("is_admin", value.isAdmin)
    }

    fun parseDeviceToken(bytes: ByteArray): DeviceToken = objectFrom(bytes).let {
        DeviceToken(it.getString("device_id"), it.getString("token"), it.getBoolean("is_admin"))
    }

    fun modes(values: List<Mode>): ByteArray = arrayBytes(values) {
        put("id", it.id); put("name", it.name); put("color", it.color); put("icon", it.icon)
        put("system_prompt", it.systemPrompt); put("response_model_id", it.responseModelId)
        put("hidden_on_watch", it.hiddenOnWatch)
    }

    fun parseModes(bytes: ByteArray): List<Mode> = parseArray(bytes) {
        Mode(
            id = getString("id"), name = getString("name"), color = getString("color"),
            icon = getString("icon"), systemPrompt = optString("system_prompt"),
            responseModelId = getString("response_model_id"),
            hiddenOnWatch = optBoolean("hidden_on_watch"),
        )
    }

    fun chats(values: List<Chat>): ByteArray = arrayBytes(values) {
        put("id", it.id); put("mode_id", it.modeId); put("mode_name", it.modeName)
        put("mode_deleted", it.modeDeleted); put("title", it.title)
    }

    fun chat(value: Chat): ByteArray = chats(listOf(value))
    fun parseChat(bytes: ByteArray): Chat = parseChats(bytes).single()
    fun parseChats(bytes: ByteArray): List<Chat> = parseArray(bytes) {
        Chat(
            id = getString("id"), modeId = getString("mode_id"), modeName = getString("mode_name"),
            modeDeleted = optBoolean("mode_deleted"), title = getString("title"),
        )
    }

    fun messages(values: List<ChatMessage>): ByteArray = arrayBytes(values) {
        put("id", it.id); put("role", it.role); put("content", it.content); put("status", it.status)
    }

    fun parseMessages(bytes: ByteArray): List<ChatMessage> = parseArray(bytes) {
        ChatMessage(getString("id"), getString("role"), optString("content"), optString("status"))
    }

    fun chatSourceCandidates(values: List<ChatSourceCandidate>): ByteArray = arrayBytes(values) {
        put("id", it.id); put("title", it.title); put("url", it.url); put("preview", it.preview)
        put("content", it.content); put("truncated", it.truncated)
    }

    fun parseChatSourceCandidates(bytes: ByteArray): List<ChatSourceCandidate> = parseArray(bytes) {
        ChatSourceCandidate(getString("id"), getString("title"), getString("url"), optString("preview"), optString("content"), optBoolean("truncated"))
    }

    fun job(value: Job): ByteArray = objectBytes { put("id", value.id); put("status", value.status) }
    fun parseJob(bytes: ByteArray): Job = objectFrom(bytes).let { Job(it.getString("id"), it.getString("status")) }

    fun events(values: List<ServerEvent>): ByteArray = arrayBytes(values) {
        put("id", it.id); put("type", it.type); put("data", it.data)
    }

    fun parseEvents(bytes: ByteArray): List<ServerEvent> = parseArray(bytes) {
        ServerEvent(getLong("id"), getString("type"), getString("data"))
    }

    private fun <T> arrayBytes(values: List<T>, encode: JSONObject.(T) -> Unit): ByteArray {
        val array = JSONArray()
        values.forEach { value -> array.put(JSONObject().apply { encode(value) }) }
        return array.toString().toByteArray(Charsets.UTF_8)
    }

    private fun <T> parseArray(bytes: ByteArray, parse: JSONObject.() -> T): List<T> {
        val array = JSONArray(bytes.toString(Charsets.UTF_8))
        return (0 until array.length()).map { array.getJSONObject(it).parse() }
    }
}
