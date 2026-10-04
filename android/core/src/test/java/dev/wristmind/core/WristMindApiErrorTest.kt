package dev.wristmind.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class WristMindApiErrorTest {
    @Test
    fun `nginx html is not exposed to the user`() {
        val message = userFacingHttpError(
            502,
            "<html><head><title>502 Bad Gateway</title></head><body>nginx</body></html>",
        )

        assertEquals("Сервер временно недоступен. Попробуйте ещё раз", message)
        assertFalse(message.contains("<html>"))
    }

    @Test
    fun `json api detail is preserved`() {
        assertEquals(
            "Режим не найден",
            userFacingHttpError(404, "{\"detail\":\"Режим не найден\"}"),
        )
    }
}
