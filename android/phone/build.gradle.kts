import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use(::load)
}
val wristmindBaseUrl = localProperties.getProperty(
    "wristmind.baseUrl",
    "https://wm.xspase.ru/",
)

android {
    namespace = "dev.wristmind.phone"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.wristmind.app"
        minSdk = 30
        targetSdk = 35
        versionCode = 2
        versionName = "0.1.1"
        buildConfigField("String", "WRISTMIND_BASE_URL", "\"$wristmindBaseUrl\"")
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(project(":core"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.compose.material3:material3:1.3.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.10.2")
    implementation("com.google.android.gms:play-services-wearable:20.0.1")
    debugImplementation("androidx.compose.ui:ui-tooling:1.8.3")
}
