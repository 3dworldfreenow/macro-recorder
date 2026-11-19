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

    fun canDraw(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(ctx)

    @Suppress("DEPRECATION")
    private fun type(): Int =
        if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else WindowManager.LayoutParams.TYPE_PHONE

    private fun wm(ctx: Context) = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager

    // ================================================================ run panel
    private var panel: View? = null
    private var statusView: TextView? = null
    private var cdView: TextView? = null
    private var pauseBtn: Button? = null

    @SuppressLint("ClickableViewAccessibility")
    fun showPanel(ctx: Context, runner: Runner) {
        hidePanel(ctx)
        val app = ctx.applicationContext
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
        box.addView(r, LinearLayout.LayoutParams(Ui.dp(app, 260), LinearLayout.LayoutParams.WRAP_CONTENT))

        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            type(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        val dm = app.resources.displayMetrics
        lp.x = dm.widthPixels - Ui.dp(app, 290)
        lp.y = Ui.dp(app, 80)

        // drag the panel by its title
        var dx = 0f; var dy = 0f; var sx = 0; var sy = 0
        title.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { dx = e.rawX; dy = e.rawY; sx = lp.x; sy = lp.y }
                MotionEvent.ACTION_MOVE -> {
                    lp.x = sx + (e.rawX - dx).toInt(); lp.y = sy + (e.rawY - dy).toInt()
                    try { wm(app).updateViewLayout(box, lp) } catch (_: Exception) {}
                }
            }
            true
        }
        wm(app).addView(box, lp)
        panel = box; statusView = st; cdView = cd; pauseBtn = pb

        runner.listener = object : Runner.Listener {
            override fun onStatus(line: String) { statusView?.text = line }
            override fun onCountdown(text: String) { cdView?.text = text }
            override fun onDone(summary: String) {
                statusView?.text = summary
                cdView?.text = ""
                pauseBtn?.visibility = View.GONE
                box.postDelayed({ hidePanel(app) }, 3500)
                MainActivity.lastResult = summary
            }
        }
    }

    private fun drawPause(paused: Boolean) {
        val b = pauseBtn ?: return
        b.text = if (paused) "▶ Resume" else "⏸ Pause"
        b.background = Ui.round(if (paused) Ui.GREEN else Ui.ORANGE, Ui.dp(b.context, 10).toFloat())
    }

    fun hidePanel(ctx: Context) {
        val v = panel ?: return
        try { wm(ctx.applicationContext).removeView(v) } catch (_: Exception) {}
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
        val app = ctx.applicationContext
        hidePick(app)
        val bar = Ui.col(app)
        bar.background = Ui.round(0xF01E3A5F.toInt(), Ui.dp(app, 14).toFloat())
        val p = Ui.dp(app, 12)
        bar.setPadding(p, p, p, p)
        bar.addView(Ui.label(app, prompt, 15f, true, Color.WHITE))
        bar.addView(Ui.label(app, "Open the screen you want, then tap 📍 PICK and tap the spot.",
            13f, false, 0xFFCFE0F5.toInt()))
        val r = Ui.row(app)
        r.addView(Ui.weight(Ui.button(app, "📍 PICK", Ui.GREEN) { showCatcher(app, done, cancel) }))
        r.addView(Ui.weight(Ui.button(app, "Cancel", Ui.GREY) { hidePick(app); cancel() }))
        bar.addView(r)
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT,
            type(), WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.BOTTOM
        lp.y = Ui.dp(app, 40)
        wm(app).addView(bar, lp)
        pickBar = bar
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun showCatcher(app: Context, done: (Int, Int) -> Unit, cancel: () -> Unit) {
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
            type(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        if (Build.VERSION.SDK_INT >= 28) {
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        wm(app).addView(layer, lp)
        pickCatcher = layer
    }

    fun hidePick(ctx: Context) {
        val app = ctx.applicationContext
        pickBar?.let { try { wm(app).removeView(it) } catch (_: Exception) {} }
        pickCatcher?.let { try { wm(app).removeView(it) } catch (_: Exception) {} }
        pickBar = null; pickCatcher = null
    }
}
