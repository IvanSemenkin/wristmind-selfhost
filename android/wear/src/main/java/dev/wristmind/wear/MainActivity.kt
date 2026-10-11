package dev.wristmind.wear

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognizerIntent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.viewModels
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val wearViewModel: WearViewModel by viewModels()
    private lateinit var screenWakeController: ScreenWakeController
    private var speechResult: ((String?) -> Unit)? = null
    private var speechInFlight = false
    private val speechLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val transcript = if (result.resultCode == Activity.RESULT_OK) {
            result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
                ?.trim()
                ?.takeIf(String::isNotEmpty)
        } else {
            null
        }
        speechInFlight = false
        speechResult?.invoke(transcript)
        speechResult = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        rememberInstallChallenge(intent)
        screenWakeController = ScreenWakeController(this)
        setContent {
            WristMindWearApp(
                screenWakeController = screenWakeController,
                launchSystemSpeech = ::launchSystemSpeech,
                vm = wearViewModel,
            )
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        rememberInstallChallenge(intent)
    }

    private fun rememberInstallChallenge(intent: Intent?) {
        val nonce = intent?.getStringExtra("wristmind_install_nonce") ?: return
        if (!InstallChallenge.valid(nonce)) return
        val prefs = getSharedPreferences("wristmind_install", 0)
        synchronized(prefs) {
            prefs.edit().putString("nonce", nonce)
                .putLong("expires", android.os.SystemClock.elapsedRealtime() + InstallChallenge.LIFETIME_MS).apply()
        }
    }

    override fun onStart() {
        super.onStart()
        screenWakeController.onForeground()
        wearViewModel.onAppForegrounded()
    }

    override fun onStop() {
        screenWakeController.onBackground()
        super.onStop()
    }

    override fun onUserInteraction() {
        super.onUserInteraction()
        screenWakeController.onInteraction()
    }

    private fun launchSystemSpeech(onResult: (String?) -> Unit) {
        if (speechInFlight) return
        speechInFlight = true
        speechResult = onResult
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            // WristMind does not offer offline speech recognition. Let Wear OS
            // choose its working Russian recognizer (normally the network one)
            // instead of forcing an unavailable downloaded model.
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale("ru", "RU").toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        runCatching { speechLauncher.launch(intent) }
            .onFailure {
                speechInFlight = false
                speechResult?.invoke(null)
                speechResult = null
            }
    }

}

class ScreenWakeController(private val activity: ComponentActivity) {
    private val handler = Handler(Looper.getMainLooper())
    private var foreground = false
    private var operationActive = false
    private val release = Runnable { if (!operationActive) clearFlag() }

    fun onForeground() {
        foreground = true
        onInteraction()
    }

    fun onBackground() {
        foreground = false
        handler.removeCallbacks(release)
        clearFlag()
    }

    fun onInteraction() {
        if (!foreground) return
        setFlag()
        handler.removeCallbacks(release)
        if (!operationActive) handler.postDelayed(release, IDLE_KEEP_SCREEN_MS)
    }

    fun setOperationActive(active: Boolean) {
        operationActive = active
        if (!foreground) return
        handler.removeCallbacks(release)
        if (active) setFlag() else onInteraction()
    }

    private fun setFlag() {
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun clearFlag() {
        activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private companion object { const val IDLE_KEEP_SCREEN_MS = 180_000L }
}
