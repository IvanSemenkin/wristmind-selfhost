package dev.wristmind.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class ChatSummary(
    val id: Long,
    val title: String,
    val updatedAt: Long,
    val preview: String,
)

data class ChatExchange(
    val id: Long,
    val userText: String,
    val assistantText: String,
    val createdAt: Long,
)

class ChatStore(context: Context) : SQLiteOpenHelper(
    context.applicationContext,
    "wristmind_chats.db",
    null,
    1,
) {
    private val preferences = context.applicationContext
        .getSharedPreferences("wristmind_chats", Context.MODE_PRIVATE)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE TABLE exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX exchanges_chat_time ON exchanges(chat_id, created_at)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    @Synchronized
    fun activeChatId(): Long {
        val stored = preferences.getLong(PREF_ACTIVE_CHAT, 0)
        if (stored > 0 && chatExists(stored)) return stored
        return createChat()
    }

    @Synchronized
    fun activeChatTitle(): String {
        val id = activeChatId()
        readableDatabase.rawQuery("SELECT title FROM chats WHERE id = ?", arrayOf(id.toString())).use {
            return if (it.moveToFirst()) it.getString(0) else "Новый диалог"
        }
    }

    @Synchronized
    fun createChat(): Long {
        val now = System.currentTimeMillis()
        val title = "Диалог ${SimpleDateFormat("dd.MM · HH:mm", Locale("ru")).format(Date(now))}"
        val id = writableDatabase.insertOrThrow(
            "chats",
            null,
            ContentValues().apply {
                put("title", title)
                put("created_at", now)
                put("updated_at", now)
            },
        )
        setActiveChat(id)
        return id
    }

    @Synchronized
    fun setActiveChat(id: Long) {
        if (chatExists(id)) {
            preferences.edit().putLong(PREF_ACTIVE_CHAT, id).apply()
        }
    }

    @Synchronized
    fun deleteChat(id: Long): Boolean {
        if (!chatExists(id)) return false
        val wasActive = preferences.getLong(PREF_ACTIVE_CHAT, 0) == id
        val db = writableDatabase
        var deleted = false
        db.beginTransaction()
        try {
            db.delete("exchanges", "chat_id = ?", arrayOf(id.toString()))
            deleted = db.delete("chats", "id = ?", arrayOf(id.toString())) > 0
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        if (!deleted) return false

        if (wasActive || !chatExists(preferences.getLong(PREF_ACTIVE_CHAT, 0))) {
            val replacement = readableDatabase.rawQuery(
                "SELECT id FROM chats ORDER BY updated_at DESC LIMIT 1",
                null,
            ).use { cursor ->
                if (cursor.moveToFirst()) cursor.getLong(0) else 0L
            }
            if (replacement > 0) {
                preferences.edit().putLong(PREF_ACTIVE_CHAT, replacement).apply()
            } else {
                preferences.edit().remove(PREF_ACTIVE_CHAT).apply()
                createChat()
            }
        }
        return true
    }

    @Synchronized
    fun addExchange(userText: String, assistantText: String): Long {
        val chatId = activeChatId()
        val now = System.currentTimeMillis()
        val db = writableDatabase
        val exchangeId = db.insertOrThrow(
            "exchanges",
            null,
            ContentValues().apply {
                put("chat_id", chatId)
                put("user_text", userText.trim())
                put("assistant_text", assistantText.trim())
                put("created_at", now)
            },
        )
        val exchangeCount = db.rawQuery(
            "SELECT COUNT(*) FROM exchanges WHERE chat_id = ?",
            arrayOf(chatId.toString()),
        ).use { cursor ->
            cursor.moveToFirst()
            cursor.getInt(0)
        }
        val values = ContentValues().apply {
            put("updated_at", now)
            if (exchangeCount == 1) put("title", compact(userText, 48))
        }
        db.update("chats", values, "id = ?", arrayOf(chatId.toString()))
        return exchangeId
    }

    @Synchronized
    fun listChats(limit: Int = 30): List<ChatSummary> {
        val result = mutableListOf<ChatSummary>()
        readableDatabase.rawQuery(
            """
            SELECT c.id, c.title, c.updated_at,
                   COALESCE((SELECT user_text FROM exchanges e
                     WHERE e.chat_id = c.id ORDER BY e.created_at DESC LIMIT 1), '')
            FROM chats c
            ORDER BY c.updated_at DESC
            LIMIT ?
            """.trimIndent(),
            arrayOf(limit.toString()),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                result += ChatSummary(
                    id = cursor.getLong(0),
                    title = cursor.getString(1),
                    updatedAt = cursor.getLong(2),
                    preview = cursor.getString(3),
                )
            }
        }
        return result
    }

    @Synchronized
    fun listExchanges(chatId: Long = activeChatId(), limit: Int = 20): List<ChatExchange> {
        val descending = mutableListOf<ChatExchange>()
        readableDatabase.rawQuery(
            """
            SELECT id, user_text, assistant_text, created_at
            FROM exchanges
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """.trimIndent(),
            arrayOf(chatId.toString(), limit.toString()),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                descending += ChatExchange(
                    id = cursor.getLong(0),
                    userText = cursor.getString(1),
                    assistantText = cursor.getString(2),
                    createdAt = cursor.getLong(3),
                )
            }
        }
        return descending.reversed()
    }

    @Synchronized
    fun recentForWatch(limit: Int = 5): JSONArray {
        val items = listExchanges(limit = limit)
        return JSONArray().apply {
            items.forEach { exchange ->
                put(
                    JSONObject()
                        .put("id", exchange.id)
                        .put("question", compact(exchange.userText, 180))
                        .put("answer", sentencePreview(exchange.assistantText, 260))
                        .put("created_at", exchange.createdAt),
                )
            }
        }
    }

    @Synchronized
    fun contextForModel(limit: Int = 6): JSONArray {
        val items = listExchanges(limit = limit)
        return JSONArray().apply {
            items.forEach { exchange ->
                put(
                    JSONObject()
                        .put("role", "user")
                        .put("content", compact(exchange.userText, 2000)),
                )
                put(
                    JSONObject()
                        .put("role", "assistant")
                        .put("content", compact(exchange.assistantText, 4000)),
                )
            }
        }
    }

    @Synchronized
    fun chatsForWatch(limit: Int = 12): JSONArray =
        JSONArray().apply {
            listChats(limit).forEach { chat ->
                put(
                    JSONObject()
                        .put("id", chat.id)
                        .put("title", compact(chat.title, 80))
                        .put("preview", compact(chat.preview, 120)),
                )
            }
        }

    @Synchronized
    fun exchange(id: Long): ChatExchange? =
        readableDatabase.rawQuery(
            """
            SELECT id, user_text, assistant_text, created_at
            FROM exchanges
            WHERE id = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(id.toString()),
        ).use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            ChatExchange(
                id = cursor.getLong(0),
                userText = cursor.getString(1),
                assistantText = cursor.getString(2),
                createdAt = cursor.getLong(3),
            )
        }

    private fun chatExists(id: Long): Boolean =
        readableDatabase.rawQuery(
            "SELECT 1 FROM chats WHERE id = ? LIMIT 1",
            arrayOf(id.toString()),
        ).use { it.moveToFirst() }

    private fun compact(value: String, limit: Int): String {
        val clean = value.replace(Regex("""\s+"""), " ").trim()
        return if (clean.length <= limit) clean else "${clean.take(limit - 1)}…"
    }

    private fun sentencePreview(value: String, limit: Int): String {
        val clean = value.replace(Regex("""\s+"""), " ").trim()
        if (clean.length <= limit) return clean
        val prefix = clean.take(limit)
        val sentenceEnd = Regex("""[.!?](?:\s|$)""")
            .findAll(prefix)
            .lastOrNull()
            ?.range
            ?.first
        val complete = sentenceEnd?.let { prefix.take(it + 1).trim() }.orEmpty()
        if (complete.length >= limit / 3) return complete
        val wordSafe = clean.take(limit - 1).substringBeforeLast(' ').trim()
        return "$wordSafe…"
    }

    companion object {
        private const val PREF_ACTIVE_CHAT = "active_chat_id"
    }
}
