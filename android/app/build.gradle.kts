import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use(::load)
}
val wristmindBaseUrl = localProperties.getProperty(
    "wristmind.baseUrl",
    "http://10.0.2.2:8000/"
)
val wristmindApiToken = localProperties.getProperty("wristmind.apiToken", "")

android {
    namespace = "dev.wristmind.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.wristmind.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 17
        versionName = "0.7.4"
        buildConfigField("String", "WRISTMIND_BASE_URL", "\"$wristmindBaseUrl\"")
        buildConfigField("String", "WRISTMIND_API_TOKEN", "\"$wristmindApiToken\"")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("io.noties.markwon:core:4.6.2")
    implementation("io.noties.markwon:inline-parser:4.6.2")
    implementation("io.noties.markwon:ext-latex:4.6.2")
}
