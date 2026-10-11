package dev.wristmind.wear

internal object InstallChallenge {
    const val LIFETIME_MS = 600000L
    fun valid(nonce: String) = nonce.matches(Regex("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"))
    fun accepts(expected: String?, incoming: String, expires: Long, now: Long): Boolean =
        valid(incoming) && expected == incoming && expires - now in 1..LIFETIME_MS
}
