package com.keypresser.touch

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.random.Random

/** Plays one sequence in the background. */
class Runner(
    private val ctx: Context,
    private val seq: JSONObject,
    private val delaySec: Int,
    private val logFile: File?,
) : Thread() {

    interface Listener {
        fun onStatus(line: String)
        fun onCountdown(text: String)
        fun onDone(summary: String)
    }

    @Volatile var stopFlag = false
    @Volatile var paused = false
    var listener: Listener? = null

    private val main = Handler(Looper.getMainLooper())
    private var loop = 0
    private var total = ""
    private var stopReason = ""
    private val n = mutableMapOf("tap" to 0, "app" to 0, "link" to 0, "find" to 0, "read" to 0)

    private fun log(s: String) {
        val f = logFile ?: return
        try {
            f.appendText("%.3f %s\n".format(System.currentTimeMillis() / 1000.0, s))
        } catch (_: Exception) {
        }
    }

    private fun status(s: String) = main.post { listener?.onStatus(s) }
    private fun countdown(s: String) = main.post { listener?.onCountdown(s) }

    private fun gate() {
        while (paused && !stopFlag) Thread.sleep(50)
    }

    /** Wait that freezes while paused and shows a countdown. */
    private fun waitSec(sec: Double, what: String): Boolean {
        var left = sec
        var last = SystemClock.uptimeMillis()
        var shown = 0L
        while (left > 0 && !stopFlag) {
            Thread.sleep(40)
            val now = SystemClock.uptimeMillis()
            if (!paused) left -= (now - last) / 1000.0
            last = now
            if (what.isNotEmpty() && now - shown > 90) {
                shown = now
                countdown((if (paused) "⏸ paused · " else "⏳ ") +
                    "$what  %.1fs".format(maxOf(0.0, left)))
            }
        }
        if (what.isNotEmpty()) countdown("")
        return !stopFlag
    }

    private fun rnd(a: Double, b: Double): Double {
        val lo = minOf(a, b)
        val hi = maxOf(a, b)
        return if (hi <= lo) lo else Random.nextDouble(lo, hi)
    }

    private fun svc(): KPService? {
        val s = KPService.inst
        if (s == null) {
            stopReason = "Accessibility for KeyPresser is off"
            log("error accessibility-off")
            stopFlag = true
        }
        return s
    }

    override fun run() {
        try {
            if (delaySec > 0) waitSec(delaySec.toDouble(), "Starting")
            val loops = seq.optInt("loops", 1)
            val steps = seq.optJSONArray("steps") ?: JSONArray()
            val every = (0 until steps.length()).any { steps.getJSONObject(it).optString("run") != "once" }
            while (!stopFlag && steps.length() > 0 && (loops == 0 || loop < loops)) {
                if (loop >= 1 && !every) break
                loop++
                total = if (loops == 0) "∞" else loops.toString()
                val sig = exec(steps)
                if (sig == "stop") break
            }
        } catch (e: Exception) {
            stopReason = "Error: ${e.message}"
            log("error ${e.javaClass.simpleName} ${e.message}")
        }
        val sum = "${n["tap"]} taps · ${n["app"]} apps · ${n["link"]} links · " +
            "${n["find"]} finds · ${n["read"]} reads"
        log(if (stopFlag) "stopped $stopReason" else "done")
        val text = (if (stopFlag) "Stopped" else "Done") + " · $sum" +
            (if (stopReason.isNotEmpty()) " ($stopReason)" else "")
        main.post { listener?.onDone(text) }
    }

    private fun halt(reason: String): String {
        stopReason = reason
        stopFlag = true
        return "stop"
    }

    /** Returns null (finished), "next" (next loop) or "stop". */
    private fun exec(steps: JSONArray): String? {
        var i = 0
        while (i < steps.length() && !stopFlag) {
            val st = steps.getJSONObject(i)
            var nxt = i + 1
            if (st.optString("run") == "once" && loop > 1) { i = nxt; continue }
            val name = st.optString("name")
            val sid = i + 1
            status("Loop $loop/$total · step $sid/${steps.length()}" +
                (if (name.isNotEmpty()) " · $name" else "") + "\n" + Steps.describe(st))
            gate()
            var sig: String? = null
            val times = maxOf(1, st.optInt("times", 1))
            when (st.optString("type")) {
                "app" -> {
                    val pkg = st.optString("pkg")
                    val intent = ctx.packageManager.getLaunchIntentForPackage(pkg)
                    if (intent == null) {
                        log("seq $loop $sid app missing $pkg")
                    } else {
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        ctx.startActivity(intent)
                        n["app"] = n["app"]!! + 1
                        log("seq $loop $sid app ok $pkg")
                    }
                }
                "link" -> {
                    val url = st.optString("url")
                    val pkg = st.optString("pkg")
                    val i1 = Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    if (pkg.isNotEmpty()) i1.setPackage(pkg)
                    var ok = try { ctx.startActivity(i1); true } catch (e: ActivityNotFoundException) { false }
                    if (!ok && pkg.isNotEmpty()) {
                        i1.setPackage(null)
                        ok = try { ctx.startActivity(i1); true } catch (e: ActivityNotFoundException) { false }
                    }
                    if (ok) n["link"] = n["link"]!! + 1
                    log("seq $loop $sid link ${if (ok) "ok" else "fail"} $url")
                }
                "tap" -> {
                    val s = svc() ?: return "stop"
                    for (k in 0 until times) {
                        if (stopFlag) break
                        gate()
                        s.tap(st.optInt("x").toFloat(), st.optInt("y").toFloat(), st.optString("kind", "Tap"))
                        n["tap"] = n["tap"]!! + 1
                        log("seq $loop $sid tap ${st.optInt("x")} ${st.optInt("y")}")
                        if (k < times - 1) waitSec(rnd(st.optDouble("tmin", 0.5), st.optDouble("tmax", 1.0)),
                            "gap before tap ${k + 2} of $times")
                    }
                }
                "swipe" -> {
                    val s = svc() ?: return "stop"
                    for (k in 0 until times) {
                        if (stopFlag) break
                        gate()
                        s.swipe(st.optInt("x").toFloat(), st.optInt("y").toFloat(),
                            st.optInt("x2").toFloat(), st.optInt("y2").toFloat(), st.optLong("ms", 400))
                        log("seq $loop $sid swipe")
                        if (k < times - 1) waitSec(rnd(st.optDouble("tmin", 0.5), st.optDouble("tmax", 1.0)),
                            "gap before swipe ${k + 2} of $times")
                    }
                }
                "nav" -> {
                    val s = svc() ?: return "stop"
                    for (k in 0 until times) {
                        if (stopFlag) break
                        gate()
                        s.nav(st.optString("nav", "Back"))
                        log("seq $loop $sid nav ${st.optString("nav", "Back").replace(" ", "_")}")
                        if (k < times - 1) waitSec(rnd(st.optDouble("tmin", 0.5), st.optDouble("tmax", 1.0)),
                            "gap before ${k + 2} of $times")
                    }
                }
                "text" -> {
                    val s = svc() ?: return "stop"
                    gate()
                    val ok = s.typeText(st.optString("text"), st.optBoolean("append"), st.optBoolean("enter"))
                    log("seq $loop $sid text ${if (ok) "ok" else "nobox"}")
                }
                "find" -> {
                    val s = svc() ?: return "stop"
                    val limit = st.optDouble("timeout", 0.0)
                    var waited = 0.0
                    var target: KPService.Hit? = null
                    var count = 0
                    while (true) {
                        gate()
                        val hits = s.find(st.optString("mode", "Contains"), st.optString("keyword"))
                        count = hits.size
                        target = when (st.optString("which", "First")) {
                            "Last" -> hits.lastOrNull()
                            "Number" -> hits.getOrNull(st.optInt("n", 1) - 1)
                            else -> hits.firstOrNull()
                        }
                        if (target != null || waited >= limit || stopFlag) break
                        status("Looking for “${st.optString("keyword")}”…")
                        waitSec(0.7, "looking for “${st.optString("keyword")}”")
                        waited += 0.7
                    }
                    n["find"] = n["find"]!! + 1
                    val ok = target != null
                    if (target != null) {
                        val cx = target.rect.centerX() + st.optInt("dx", 0)
                        val cy = target.rect.centerY() + st.optInt("dy", 0)
                        s.tap(cx.toFloat(), cy.toFloat(), st.optString("kind", "Tap"))
                        n["tap"] = n["tap"]!! + 1
                        log("seq $loop $sid find found $cx $cy '${target.text.replace("\n", " ")}'")
                    } else {
                        log("seq $loop $sid find notfound $count")
                    }
                    status((if (ok) "✔ found & tapped" else "✖ not found") + " → " + Steps.action(st, ok))
                    val r = branch(st, ok, steps.length())
                    if (r.first != null) return r.first
                    if (r.second >= 0) nxt = r.second
                    sig = r.third
                }
                "read" -> {
                    val s = svc() ?: return "stop"
                    val limit = st.optDouble("timeout", 0.0)
                    var waited = 0.0
                    var text = ""
                    var ok = false
                    while (true) {
                        gate()
                        text = s.screenText()
                        ok = if (st.optString("mode") == "Number") Steps.numberRule(st, text)
                        else Steps.matches(st.optString("mode", "Contains"), st.optString("pattern"), text)
                        if (ok || waited >= limit || stopFlag) break
                        waitSec(0.7, "waiting for text")
                        waited += 0.7
                    }
                    n["read"] = n["read"]!! + 1
                    log("seq $loop $sid read ${if (ok) "match" else "nomatch"}")
                    status((if (ok) "✔ text matches" else "✖ no match") + " → " + Steps.action(st, ok))
                    val r = branch(st, ok, steps.length())
                    if (r.first != null) return r.first
                    if (r.second >= 0) nxt = r.second
                    sig = r.third
                }
            }
            if (stopFlag) return "stop"
            val gap = rnd(st.optDouble("amin", 0.0), st.optDouble("amax", 0.0))
            if (gap > 0) waitSec(gap, "wait before next step")
            if (sig != null) return sig
            i = nxt
        }
        return if (stopFlag) "stop" else null
    }

    /** (return now, next index or -1, signal) */
    private fun branch(st: JSONObject, ok: Boolean, count: Int): Triple<String?, Int, String?> {
        return when (st.optString(if (ok) "on_yes" else "on_no", if (ok) "Continue" else "Stop")) {
            "Stop" -> Triple(halt("stopped by step"), -1, null)
            "Next loop" -> Triple(null, -1, "next")
            "Go to step" -> {
                val t = st.optInt(if (ok) "yes_step" else "no_step", 1)
                Triple(null, t.coerceIn(1, count) - 1, null)
            }
            else -> Triple(null, -1, null)
        }
    }
}
