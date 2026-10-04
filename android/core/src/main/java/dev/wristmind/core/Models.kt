package dev.wristmind.core

data class DeviceToken(
    val deviceId: String,
    val token: String,
    val isAdmin: Boolean,
)

data class PairingCode(val code: String, val expiresAt: String)

data class ModelOption(val id: String, val label: String, val provider: String)

data class Mode(
    val id: String,
    val name: String,
    val color: String,
    val icon: String,
    val systemPrompt: String,
    val responseModelId: String,
    val hiddenOnWatch: Boolean = false,
)

data class Chat(
    val id: String,
    val modeId: String,
    val modeName: String,
    val modeDeleted: Boolean,
    val title: String,
)

data class ChatMessage(
    val id: String,
    val role: String,
    val content: String,
    val status: String,
)

data class Job(val id: String, val status: String)

data class FallbackTicket(val ticket: String, val expiresAt: String)

data class FallbackAnswer(
    val requestId: String,
    val answer: String,
    val degraded: Boolean,
    val sourcesAvailable: Boolean,
)

data class ChatSourceCandidate(
    val id: String,
    val title: String,
    val url: String,
    val preview: String,
    val content: String = "",
    val truncated: Boolean = false,
)

data class KnowledgeSource(
    val id: String,
    val modeId: String,
    val title: String,
    val filename: String,
    val processingMode: String,
    val status: String,
    val pageCount: Int,
    val chunkCount: Int,
)

data class ServerEvent(
    val id: Long,
    val type: String,
    val data: String,
)
