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
    "",
)

android {
    namespace = "dev.wristmind.phone"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.wristmind.app"
        minSdk = 30
        targetSdk = 35
        versionCode = 3
        versionName = "0.2.0"
        buildConfigField("String", "WRISTMIND_BASE_URL", "\"$wristmindBaseUrl\"")
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
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    constraints {
        implementation("androidx.fragment:fragment:1.8.6") {
            because("Play services requests 1.1.0, incompatible with the ActivityResult API")
        }
    }
    implementation(project(":core"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.compose.material3:material3:1.3.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.10.2")
    implementation("com.google.android.gms:play-services-wearable:20.0.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.2")
    implementation("com.github.MuntashirAkon:libadb-android:3.1.1")
    implementation("org.conscrypt:conscrypt-android:2.5.3")
    implementation("org.bouncycastle:bcpkix-jdk15to18:1.81")
    testImplementation("junit:junit:4.13.2")
    debugImplementation("androidx.compose.ui:ui-tooling:1.8.3")
}


abstract class BundleWatchApk : DefaultTask() {
    @get:InputDirectory @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val apkDirectory: DirectoryProperty
    @get:OutputDirectory abstract val outputDirectory: DirectoryProperty
    @TaskAction fun bundle() {
        val files = apkDirectory.get().asFile.listFiles().orEmpty().filter {
            it.extension == "apk" && "unsigned" !in it.name
        }
        check(files.size == 1) { "One signed Wear APK is required. Configure wristmind.signing.* in local.properties." }
        val destination = outputDirectory.get().asFile.apply { mkdirs() }.resolve("wristmind-wear.apk")
        files.single().copyTo(destination, overwrite = true)
    }
}

// Generated assets wire dependencies for packaging and lint, not just mergeAssets.
androidComponents.onVariants { variant ->
    val capitalized = variant.name.replaceFirstChar(Char::uppercaseChar)
    val bundleWatch = tasks.register<BundleWatchApk>("bundle${capitalized}Watch") {
        dependsOn(":wear:assemble$capitalized")
        apkDirectory.set(project(":wear").layout.buildDirectory.dir("outputs/apk/${variant.name}"))
        outputDirectory.set(layout.buildDirectory.dir("generated/watchAssets/${variant.name}"))
    }
    variant.sources.assets?.addGeneratedSourceDirectory(bundleWatch, BundleWatchApk::outputDirectory)
}
