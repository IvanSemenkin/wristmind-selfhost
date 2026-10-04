# WristMind Android v2

The active Gradle build contains three modules:

- `:core` — API models, SSE client, and encrypted device configuration;
- `:phone` — the administrative Android app;
- `:wear` — the standalone Wear OS client for Xiaomi Watch 2.

Both applications use `dev.wristmind.app` as their application ID so a future
Wearable Data Layer integration can use the same package and signing identity.
The primary voice path is watch `SpeechRecognizer` → text → VPS. The phone is
not in that request path.

The old `android/app` source remains on the original workstation as legacy code
but is not included by `settings.gradle.kts` and is intentionally not tracked in
the v2 repository.

For local HTTP smoke tests, set this in the ignored `local.properties`:

```properties
wristmind.baseUrl=http://192.168.4.191/
```

Use JDK 21 for Gradle. JDK 25 is not supported by the current Kotlin Gradle
plugin.
