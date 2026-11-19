package com.keypresser.touch

import org.json.JSONObject

/** Step types, how they are described, and text matching rules. */
object Steps {
    val TYPES = listOf(
        "app" to "📱 Open app",
        "link" to "🔗 Open link",
        "tap" to "👆 Tap",
        "swipe" to "↔ Swipe",
        "wait" to "⏱ Wait",
        "nav" to "◀ Back / Home",
        "text" to "⌨ Type text",
        "find" to "🎯 Find & tap",
        "read" to "🔍 Read text"
    )

    val NAV = listOf("Back", "Home", "Recent apps", "Notifications", "Quick settings")
    val TAPS = listOf("Tap", "Double tap", "Long press")
    val MATCH = listOf("Contains", "Equals", "Regex")
    val READ_MATCH = listOf("Contains", "Equals", "Regex", "Number")
    val OPS = listOf("=", ">", "<", "≥", "≤")
    val ACTIONS = listOf("Continue", "Go to step", "Next loop", "Stop")
    val WHICH = listOf("First", "Last", "Number")

    fun label(type: String): String = TYPES.firstOrNull { it.first == type }?.second ?: type

    private fun num(v: Double): String =
        if (v == Math.floor(v)) v.toLong().toString() else "%.1f".format(v)

    fun span(a: Double, b: Double): String = if (a == b) num(a) else "${num(a)}-${num(b)}"

    fun action(st: JSONObject, ok: Boolean): String {
        val a = st.optString(if (ok) "on_yes" else "on_no", if (ok) "Continue" else "Stop")
        return if (a == "Go to step") "go to step ${st.optInt(if (ok) "yes_step" else "no_step", 1)}"
        else a.lowercase()
    }

    fun describe(st: JSONObject): String {
        val times = st.optInt("times", 1)
        val d = when (st.optString("type")) {
            "app" -> "📱 Open ${st.optString("app_label", st.optString("pkg", "?"))}"
            "link" -> "🔗 ${st.optString("url")}" +
                (if (st.optString("pkg").isNotEmpty())
                    "  (in ${st.optString("app_label", st.optString("pkg"))})" else "")
            "tap" -> "👆 ${st.optString("kind", "Tap")} (${st.optInt("x")}, ${st.optInt("y")})"
            "swipe" -> "↔ Swipe (${st.optInt("x")}, ${st.optInt("y")}) → " +
                "(${st.optInt("x2")}, ${st.optInt("y2")})"
            "wait" -> "⏱ Wait"
            "nav" -> "◀ ${st.optString("nav", "Back")}"
            "text" -> "⌨ Type “${st.optString("text").take(30)}”" +
                (if (st.optBoolean("enter")) " + Enter" else "")
            "find" -> "🎯 Find “${st.optString("keyword")}” (${st.optString("which", "First").lowercase()})" +
                " → ✔ ${action(st, true)} / ✖ ${action(st, false)}"
            "read" -> {
                val m = st.optString("mode", "Contains")
                val rule = if (m == "Number") "number ${st.optString("op", "=")} ${num(st.optDouble("num", 0.0))}"
                else "${m.lowercase()} “${st.optString("pattern")}”"
                "🔍 Read: $rule → ✔ ${action(st, true)} / ✖ ${action(st, false)}"
            }
            else -> st.optString("type")
        }
        return if (times > 1 && st.optString("type") in listOf("tap", "swipe", "nav")) "$d × $times" else d
    }

    fun matches(mode: String, pattern: String, text: String): Boolean {
        return when (mode) {
            "Equals" -> norm(text) == norm(pattern) && pattern.isNotEmpty()
            "Regex" -> try {
                Regex(pattern, RegexOption.IGNORE_CASE).containsMatchIn(text)
            } catch (e: Exception) { false }
            else -> if (pattern.isEmpty()) text.isNotBlank()
            else text.contains(pattern, ignoreCase = true)
        }
    }

    private fun norm(s: String) = s.trim().replace(Regex("\\s+"), " ").lowercase()

    private val NUM = Regex("-?\\d[\\d,]*(?:\\.\\d+)?")

    fun numberRule(st: JSONObject, text: String): Boolean {
        val m = NUM.find(text) ?: return false
        val v = m.value.replace(",", "").toDoubleOrNull() ?: return false
        val n = st.optDouble("num", 0.0)
        return when (st.optString("op", "=")) {
            ">" -> v > n
            "<" -> v < n
            "≥" -> v >= n
            "≤" -> v <= n
            else -> v == n
        }
    }

    /** A sensible new step of the given type. */
    fun blank(type: String): JSONObject = JSONObject().put("type", type).put("amin", 1).put("amax", 2)
}
