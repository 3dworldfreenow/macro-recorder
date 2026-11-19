package com.keypresser.touch

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * The accessibility service: this is what lets KeyPresser tap, swipe,
 * press Back/Home, read text on screen and type into other apps.
 */
class KPService : AccessibilityService() {

    companion object {
        @Volatile
        var inst: KPService? = null
    }

    data class Hit(val text: String, val rect: Rect)

    override fun onServiceConnected() {
        super.onServiceConnected()
        inst = this
    }

    override fun onDestroy() {
        inst = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    // ------------------------------------------------------------ gestures
    private fun gesture(path: Path, durationMs: Long): Boolean {
        val g = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        val latch = CountDownLatch(1)
        var ok = false
        val sent = dispatchGesture(g, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                ok = true; latch.countDown()
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                latch.countDown()
            }
        }, null)
        if (!sent) return false
        latch.await(durationMs + 3000, TimeUnit.MILLISECONDS)
        return ok
    }

    fun tap(x: Float, y: Float, kind: String = "Tap"): Boolean {
        val p = Path().apply { moveTo(x, y) }
        return when (kind) {
            "Long press" -> gesture(p, 800)
            "Double tap" -> {
                val a = gesture(p, 50)
                Thread.sleep(90)
                a && gesture(Path().apply { moveTo(x, y) }, 50)
            }
            else -> gesture(p, 60)
        }
    }

    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, ms: Long): Boolean {
        val p = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        return gesture(p, ms.coerceIn(50, 10000))
    }

    fun nav(which: String): Boolean = performGlobalAction(
        when (which) {
            "Home" -> GLOBAL_ACTION_HOME
            "Recent apps" -> GLOBAL_ACTION_RECENTS
            "Notifications" -> GLOBAL_ACTION_NOTIFICATIONS
            "Quick settings" -> GLOBAL_ACTION_QUICK_SETTINGS
            else -> GLOBAL_ACTION_BACK
        }
    )

    // ------------------------------------------------------------ screen text
    private fun roots(): List<AccessibilityNodeInfo> {
        val out = mutableListOf<AccessibilityNodeInfo>()
        try {
            for (w in windows) {
                val r = w.root ?: continue
                if (r.packageName?.toString() == packageName) continue  // skip our overlay
                out.add(r)
            }
        } catch (_: Exception) {
        }
        if (out.isEmpty()) rootInActiveWindow?.let { out.add(it) }
        return out
    }

    private fun walk(n: AccessibilityNodeInfo?, depth: Int, f: (AccessibilityNodeInfo) -> Unit) {
        if (n == null || depth > 60) return
        f(n)
        for (i in 0 until n.childCount) walk(n.getChild(i), depth + 1, f)
    }

    private fun nodeText(n: AccessibilityNodeInfo): String {
        val t = n.text?.toString()
        if (!t.isNullOrBlank()) return t
        return n.contentDescription?.toString() ?: ""
    }

    /** All visible texts with their positions, top-to-bottom. */
    fun visibleTexts(): List<Hit> {
        val out = mutableListOf<Hit>()
        for (r in roots()) {
            walk(r, 0) { n ->
                val t = nodeText(n)
                if (t.isNotBlank() && n.isVisibleToUser) {
                    val rect = Rect()
                    n.getBoundsInScreen(rect)
                    if (rect.width() > 0 && rect.height() > 0) out.add(Hit(t.trim(), rect))
                }
            }
        }
        return out.sortedWith(compareBy({ it.rect.top / 12 }, { it.rect.left }))
    }

    fun screenText(): String = visibleTexts().joinToString("\n") { it.text }

    fun find(mode: String, keyword: String): List<Hit> =
        visibleTexts().filter { Steps.matches(mode, keyword, it.text) }

    // ------------------------------------------------------------ typing
    fun typeText(text: String, append: Boolean, enter: Boolean): Boolean {
        var target: AccessibilityNodeInfo? = null
        for (r in roots()) {
            target = r.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            if (target != null) break
        }
        if (target == null) {
            // no focused box: use the first editable box on screen
            for (r in roots()) {
                walk(r, 0) { n -> if (target == null && n.isEditable && n.isVisibleToUser) target = n }
                if (target != null) break
            }
        }
        val t = target ?: return false
        if (!t.isFocused) t.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        val now = if (append) (t.text?.toString() ?: "") else ""
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, now + text)
        var ok = t.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        if (!ok) {
            // fall back to clipboard + paste
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("KeyPresser", text))
            ok = t.performAction(AccessibilityNodeInfo.ACTION_PASTE)
        }
        if (enter && Build.VERSION.SDK_INT >= 30) {
            Thread.sleep(150)
            t.performAction(android.R.id.accessibilityActionImeEnter)
        }
        return ok
    }
}
