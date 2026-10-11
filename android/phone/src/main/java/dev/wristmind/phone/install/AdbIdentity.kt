package dev.wristmind.phone.install

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.bouncycastle.asn1.x500.X500Name
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder
import org.bouncycastle.jce.provider.BouncyCastleProvider
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder
import java.math.BigInteger
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.cert.Certificate
import java.security.cert.CertificateFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Date
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.io.DataInputStream
import java.io.DataOutputStream

/** Private ADB identity encrypted with a non-exportable Android Keystore AES key. */
internal class AdbIdentity(context: Context) {
    val privateKey: PrivateKey
    val certificate: Certificate
    init {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val alias = "wristmind_adb_identity"
        val wrappingKey = (keyStore.getKey(alias, null) as? SecretKey) ?: KeyGenerator
            .getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            }.generateKey()
        val file = AtomicFile(context.noBackupFilesDir.resolve("adb-identity"))
        if (file.baseFile.exists()) {
            val bytes = file.readFully()
            val decoded = Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, wrappingKey, GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
                doFinal(bytes.copyOfRange(12, bytes.size))
            }
            DataInputStream(decoded.inputStream()).use { input ->
                val size = input.readInt()
                require(size in 1..16384)
                privateKey = KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(ByteArray(size).also(input::readFully)))
                certificate = CertificateFactory.getInstance("X.509").generateCertificate(input)
            }
        } else {
            val pair = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
            val provider = BouncyCastleProvider()
            val name = X500Name("CN=WristMind Companion")
            val builder = JcaX509v3CertificateBuilder(name, BigInteger.valueOf(System.currentTimeMillis()),
                Date(System.currentTimeMillis() - 86400000), Date(System.currentTimeMillis() + 10L * 365 * 86400000), name, pair.public)
            certificate = JcaX509CertificateConverter().setProvider(provider).getCertificate(builder.build(
                JcaContentSignerBuilder("SHA256withRSA").setProvider(provider).build(pair.private)))
            privateKey = pair.private
            val raw = java.io.ByteArrayOutputStream().apply {
                DataOutputStream(this).use { it.writeInt(privateKey.encoded.size); it.write(privateKey.encoded); it.write(certificate.encoded) }
            }.toByteArray()
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, wrappingKey) }
            val encrypted = cipher.doFinal(raw)
            val stream = file.startWrite()
            try { stream.write(cipher.iv + encrypted); file.finishWrite(stream) }
            catch (error: Exception) { file.failWrite(stream); throw error }
        }
    }
}
