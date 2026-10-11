package dev.wristmind.wear

import org.json.JSONObject

/** The watch presents a chart's data-backed description, never executable content. */
internal fun chartSummary(source: String): String? = runCatching {
    require(source.length <= 100_000)
    val chart = JSONObject(source)
    val title = chart.getString("title").take(160)
    val summary = chart.getString("summary").take(1000)
    val points = chart.getJSONArray("points")
    require(points.length() in 2..500)
    for (i in 0 until points.length()) {
        val point = points.getJSONArray(i)
        require(point.length() == 2)
        for (j in 0..1) {
            val value = point.get(j)
            require(value is Number && value.toDouble().isFinite() && kotlin.math.abs(value.toDouble()) <= 1e12)
        }
    }
    "График: $title. $summary"
}.getOrNull()
