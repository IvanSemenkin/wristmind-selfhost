plugins {
    id("com.android.application")
}

android {
    namespace = "dev.wristmind.panel"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.wristmind.panel"
        minSdk = 23
        targetSdk = 35
        versionCode = 4
        versionName = "0.1.3"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.7.3")
}
