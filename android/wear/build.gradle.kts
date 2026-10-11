import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.gms.google-services") apply false
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use(::load)
}
if (file("google-services.json").exists()) apply(plugin = "com.google.gms.google-services")

val wristmindBaseUrl = localProperties.getProperty(
    "wristmind.baseUrl",
    "https://server.example.invalid/",
)

android {
    namespace = "dev.wristmind.wear"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.wristmind.app"
        minSdk = 30
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0"
        buildConfigField("String", "WRISTMIND_BASE_URL", "\"$wristmindBaseUrl\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (localProperties.getProperty("wristmind.signing.storeFile") != null) {
            create("selfhost") {
                storeFile = rootProject.file(localProperties.getProperty("wristmind.signing.storeFile"))
                storePassword = localProperties.getProperty("wristmind.signing.storePassword")
                keyAlias = localProperties.getProperty("wristmind.signing.keyAlias")
                keyPassword = localProperties.getProperty("wristmind.signing.keyPassword")
            }
        }
    }
    buildTypes.getByName("release") {
        signingConfig = signingConfigs.findByName("selfhost")
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    constraints {
        implementation("androidx.fragment:fragment:1.8.6") {
            because("Play services requests 1.1.0, incompatible with the ActivityResult API")
        }
    }
    implementation(project(":core"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.foundation:foundation:1.8.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.2")
    implementation("androidx.wear.compose:compose-foundation:1.6.2")
    implementation("androidx.wear.compose:compose-material3:1.6.2")
    implementation("androidx.wear.compose:compose-navigation:1.6.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.10.2")
    implementation("com.google.android.gms:play-services-wearable:20.0.1")
    implementation(platform("com.google.firebase:firebase-bom:34.18.0"))
    implementation("com.google.firebase:firebase-messaging")

    debugImplementation("androidx.compose.ui:ui-tooling:1.8.3")
    compileOnly("androidx.wear.compose:compose-ui-tooling:1.6.2")
    debugImplementation("androidx.wear.compose:compose-ui-tooling:1.6.2")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("org.robolectric:robolectric:4.15.1")
}
