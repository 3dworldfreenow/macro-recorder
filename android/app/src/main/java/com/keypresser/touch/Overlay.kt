package com.keypresser.touch

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/** Floating windows drawn over other apps. */
object Overlay {

    /** We can show floating windows if Accessibility is on (best: shown even
     *  over Settings) or the "display over other apps" permission is given. */
    fun canDraw(ctx: Context): Boolean =
        KPService.inst != null || Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(ctx)

    /** Context + window type to use: the accessibility service if it is on. */
    @Suppress("DEPRECATION")
    private fun host(ctx: Context): Pair<Context, Int> {
        val svc = KPService.inst
        if (svc != null) return svc to WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
        return ctx.applicationContext to
            (if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else WindowManager.LayoutParams.TYPE_PHONE)
    }

    private fun wm(ctx: Context) = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager

    // each window remembers the WindowManager it was added with
    private val owners = HashMap<View, WindowManager>()

    private fun add(wmgr: WindowManager, v: View, lp: WindowManager.LayoutParams) {
        wmgr.addView(v, lp)
        owners[v] = wmgr
    }

    private fun remove(v: View?) {
        if (v == null) return
        try { owners[v]?.removeView(v) } catch (_: Exception) {}
        owners.remove(v)
    }

    // ================================================================ run panel
    private var panel: View? = null
    private var statusView: TextView? = null
    private var cdView: TextView? = null
    private var pauseBtn: Button? = null

    @SuppressLint("ClickableViewAccessibility")
    fun showPanel(ctx: Context, runner: Runner) {
        hidePanel(ctx)
        val (app, wtype) = host(ctx)
        val wmgr = wm(app)
        val box = Ui.col(app)
        box.background = Ui.round(0xEE1F2A30.toInt(), Ui.dp(app, 14).toFloat())
        val p = Ui.dp(app, 10)
        box.setPadding(p, p, p, p)

        val title = Ui.label(app, "⠿  KeyPresser", 14f, true, 0xFF9FB3BF.toInt())
        box.addView(title)
        val st = Ui.label(app, "Starting…", 13f, false, Color.WHITE)
        st.maxWidth = Ui.dp(app, 260)
        box.addView(st)
        val cd = Ui.label(app, "", 15f, true, 0xFFFFD54F.toInt())
        box.addView(cd)
        val r = Ui.row(app)
        val pb = Ui.button(app, "⏸ Pause", Ui.ORANGE, size = 15f) {
            runner.paused = !runner.paused
            drawPause(runner.paused)
        }
        val sb = Ui.button(app, "■ Stop", Ui.RED, size = 15f) {
            runner.stopFlag = true
            runner.paused = false
        }
        r.addView(Ui.weight(pb))
        r.addView(Ui.weight(sb))
        val dm = app.resources.displayMetrics
        val panelW = minOf(Ui.dp(app, 260), dm.widthPixels - Ui.dp(app, 40))
        st.maxWidth = panelW
        box.addView(r, LinearLayout.LayoutParams(panelW, LinearLayout.LayoutParams.WRAP_CONTENT))

        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            wtype,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        // keep it inside the screen on any phone size (top-right corner)
        lp.x = maxOf(0, dm.widthPixels - panelW - Ui.dp(app, 36))
        lp.y = Ui.dp(app, 80)

        // drag the panel by its title
        var dx = 0f; var dy = 0f; var sx = 0; var sy = 0
        title.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { dx = e.rawX; dy = e.rawY; sx = lp.x; sy = lp.y }
                MotionEvent.ACTION_MOVE -> {
                    lp.x = sx + (e.rawX - dx).toInt(); lp.y = sy + (e.rawY - dy).toInt()
                    try { wmgr.updateViewLayout(box, lp) } catch (_: Exception) {}
                }
            }
            true
        }
        add(wmgr, box, lp)
        panel = box; statusView = st; cdView = cd; pauseBtn = pb

        runner.listener = object : Runner.Listener {
            override fun onStatus(line: String) { statusView?.text = line }
            override fun onCountdown(text: String) { cdView?.text = text }
            override fun onDone(summary: String) {
                statusView?.text = summary
                cdView?.text = ""
                pauseBtn?.visibility = View.GONE
                box.postDelayed({ if (panel === box) hidePanel(app) else remove(box) }, 3500)
                MainActivity.lastResult = summary
            }
        }
    }

    private fun drawPause(paused: Boolean) {
        val b = pauseBtn ?: return
        b.text = if (paused) "▶ Resume" else "⏸ Pause"
        b.background = Ui.round(if (paused) Ui.GREEN else Ui.ORANGE, Ui.dp(b.context, 10).toFloat())
    }

    fun hidePanel(@Suppress("UNUSED_PARAMETER") ctx: Context) {
        remove(panel)
        panel = null; statusView = null; cdView = null; pauseBtn = null
    }

    // ================================================================ picker
    private var pickBar: View? = null
    private var pickCatcher: View? = null

    /**
     * Step 1: a small bar "go to your screen, then tap PICK".
     * Step 2: a see-through layer; the next tap gives its position.
     */
    @SuppressLint("ClickableViewAccessibility")
    fun pick(ctx: Context, prompt: String, done: (Int, Int) -> Unit, cancel: () -> Unit) {
        hidePick(ctx)
        val (app, wtype) = host(ctx)
        val bar = Ui.col(app)
        bar.background = Ui.round(0xF01E3A5F.toInt(), Ui.dp(app, 14).toFloat())
        val p = Ui.dp(app, 12)
        bar.setPadding(p, p, p, p)
        bar.addView(Ui.label(app, prompt, 15f, true, Color.WHITE))
        bar.addView(Ui.label(app, "Open the screen you want, then tap 📍 PICK and tap the spot.",
            13f, false, 0xFFCFE0F5.toInt()))
        val r = Ui.row(app)
        r.addView(Ui.weight(Ui.button(app, "📍 PICK", Ui.GREEN) { showCatcher(app, wtype, done) }))
        r.addView(Ui.weight(Ui.button(app, "Cancel", Ui.GREY) { hidePick(app); cancel() }))
        bar.addView(r)
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT,
            wtype, WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.BOTTOM
        lp.y = Ui.dp(app, 40)
        add(wm(app), bar, lp)
        pickBar = bar
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun showCatcher(app: Context, wtype: Int, done: (Int, Int) -> Unit) {
        pickBar?.visibility = View.GONE
        val layer = FrameLayout(app)
        layer.setBackgroundColor(0x55000000)
        val tip = Ui.label(app, "Tap the spot", 20f, true, Color.WHITE)
        tip.setBackgroundColor(0xCC1E3A5F.toInt())
        tip.setPadding(Ui.dp(app, 16), Ui.dp(app, 10), Ui.dp(app, 16), Ui.dp(app, 10))
        layer.addView(tip, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.CENTER_HORIZONTAL).apply {
            topMargin = Ui.dp(app, 60)
        })
        layer.setOnTouchListener { _, e ->
            if (e.action == MotionEvent.ACTION_UP) {
                val x = e.rawX.toInt(); val y = e.rawY.toInt()
                hidePick(app)
                done(x, y)
            }
            true
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
            wtype,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        if (Build.VERSION.SDK_INT >= 28) {
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        add(wm(app), layer, lp)
        pickCatcher = layer
    }

    fun hidePick(@Suppress("UNUSED_PARAMETER") ctx: Context) {
        remove(pickBar)
        remove(pickCatcher)
        pickBar = null; pickCatcher = null
    }
}
