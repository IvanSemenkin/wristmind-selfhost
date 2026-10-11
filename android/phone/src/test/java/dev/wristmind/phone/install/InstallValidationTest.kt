package dev.wristmind.phone.install

import org.junit.Assert.*
import org.junit.Test

class InstallValidationTest {
    @Test fun serverRequiresHttpsRootWithoutCredentials() {
        assertEquals("https://ai.example.com", InstallValidation.server(" https://ai.example.com/ "))
        listOf("http://ai.example.com", "https://user:secret@ai.example.com", "https://ai.example.com/v1",
            "https://ai.example.com?secret=x", "https://ai.example.com:99999", "https://ai.example.com:0", "https://ai.example.com#x", "", "https://").forEach {
            assertThrows(IllegalArgumentException::class.java) { InstallValidation.server(it) }
        }
    }
    @Test fun validatesAddressAndDynamicPort() {
        assertEquals("192.168.0.218", InstallValidation.host("192.168.0.218"))
        assertEquals(37267, InstallValidation.port("37267"))
        listOf("localhost", "127.0.0.1", "256.1.1.1", "192.168.0.1;rm", "0.0.0.0", "224.0.0.1").forEach {
            assertThrows(IllegalArgumentException::class.java) { InstallValidation.host(it) }
        }
        listOf("", "0", "65536", "-1", "5555;echo").forEach {
            assertThrows(IllegalArgumentException::class.java) { InstallValidation.port(it) }
        }
    }
    @Test fun refusesPhoneAndOldWatch() {
        InstallValidation.compatible(30, "feature:android.hardware.type.watch\nfeature:android.hardware.microphone", 30)
        assertThrows(IllegalArgumentException::class.java) { InstallValidation.compatible(29, "feature:android.hardware.type.watch", 30) }
        assertThrows(IllegalArgumentException::class.java) { InstallValidation.compatible(35, "feature:android.hardware.telephony", 30) }
    }
    @Test fun updateFailuresPreserveDataAndGiveUsefulReason() {
        InstallValidation.installationResult("Success\n")
        val mismatch = assertThrows(IllegalArgumentException::class.java) {
            InstallValidation.installationResult("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]")
        }
        assertTrue(mismatch.message!!.contains("Данные сохранены"))
        listOf("", "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]", "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]").forEach {
            assertThrows(IllegalArgumentException::class.java) { InstallValidation.installationResult(it) }
        }
    }
}
