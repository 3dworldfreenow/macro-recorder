package com.keypresser.touch

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** Small helpers so the screens can be built in code (big, touch-friendly). */
object Ui {
    const val GREEN = 0xFF2E7D32.toInt()
    const val RED = 0xFFC62828.toInt()
    const val BLUE = 0xFF1565C0.toInt()
    const val ORANGE = 0xFFEF6C00.toInt()
    const val GREY = 0xFF9E9E9E.toInt()
    const val DARK = 0xFF37474F.toInt()
    const val SOFT = 0xFFE3E8EF.toInt()
    const val BG = 0xFFF4F6F9.toInt()

    fun dp(ctx: Context, v: Int): Int = (v * ctx.resources.displayMetrics.density).toInt()

    fun round(color: Int, radius: Float): GradientDrawable =
        GradientDrawable().apply { setColor(color); cornerRadius = radius }

    fun button(ctx: Context, text: String, color: Int = BLUE, textColor: Int = Color.WHITE,
               size: Float = 16f, onClick: () -> Unit): Button {
        val b = Button(ctx)
        b.text = text
        b.isAllCaps = false
        b.textSize = size
        b.setTextColor(textColor)
        b.setTypeface(b.typeface, Typeface.BOLD)
        b.background = round(color, dp(ctx, 10).toFloat())
        b.setPadding(dp(ctx, 12), dp(ctx, 10), dp(ctx, 12), dp(ctx, 10))
        b.minHeight = dp(ctx, 48)
        b.setOnClickListener { onClick() }
        return b
    }

    fun soft(ctx: Context, text: String, onClick: () -> Unit): Button =
        button(ctx, text, SOFT, 0xFF1A1A1A.toInt(), 15f, onClick)

    fun label(ctx: Context, text: String, size: Float = 15f, bold: Boolean = false,
              color: Int = 0xFF1A1A1A.toInt()): TextView {
        val t = TextView(ctx)
        t.text = text
        t.textSize = size
        t.setTextColor(color)
        if (bold) t.setTypeface(t.typeface, Typeface.BOLD)
        t.setPadding(0, dp(ctx, 6), 0, dp(ctx, 2))
        return t
    }

    fun edit(ctx: Context, value: String, hint: String = "", number: Boolean = false,
             decimal: Boolean = false, signed: Boolean = false, multi: Boolean = false): EditText {
        val e = EditText(ctx)
        e.setText(value)
        e.hint = hint
        e.textSize = 17f
        e.background = GradientDrawable().apply {
            setColor(Color.WHITE); cornerRadius = dp(ctx, 8).toFloat()
            setStroke(dp(ctx, 1), 0xFFB0BEC5.toInt())
        }
        e.setPadding(dp(ctx, 10), dp(ctx, 10), dp(ctx, 10), dp(ctx, 10))
        e.inputType = when {
            number -> InputType.TYPE_CLASS_NUMBER or
                (if (decimal) InputType.TYPE_NUMBER_FLAG_DECIMAL else 0) or
                (if (signed) InputType.TYPE_NUMBER_FLAG_SIGNED else 0)
            multi -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            else -> InputType.TYPE_CLASS_TEXT
        }
        if (multi) { e.minLines = 2; e.gravity = Gravity.TOP or Gravity.START }
        return e
    }

    fun row(ctx: Context): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun col(ctx: Context): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
    }

    fun weight(v: View, w: Float = 1f, marginDp: Int = 3): View {
        val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, w)
        val m = dp(v.context, marginDp)
        lp.setMargins(m, m, m, m)
        v.layoutParams = lp
        return v
    }

    fun full(v: View, topDp: Int = 4): View {
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT)
        lp.topMargin = dp(v.context, topDp)
        v.layoutParams = lp
        return v
    }

    /** A row of choice buttons; the selected one is blue. */
    class Choice(ctx: Context, options: List<String>, selected: String, cols: Int = 3,
                 val onChange: (String) -> Unit = {}) : LinearLayout(ctx) {
        var value: String = selected
            private set
        private val buttons = mutableMapOf<String, Button>()

        init {
            orientation = VERTICAL
            var r: LinearLayout? = null
            options.forEachIndexed { i, opt ->
                if (i % cols == 0) { r = row(ctx); addView(r) }
                val b = Button(ctx)
                b.text = opt
                b.isAllCaps = false
                b.textSize = 14f
                b.setPadding(dp(ctx, 4), dp(ctx, 8), dp(ctx, 4), dp(ctx, 8))
                b.minHeight = dp(ctx, 46)
                b.setOnClickListener { set(opt) }
                r!!.addView(weight(b))
                buttons[opt] = b
            }
            val rest = (cols - options.size % cols) % cols
            repeat(rest) { r!!.addView(weight(View(ctx))) }
            draw()
        }

        fun set(v: String) {
            value = v
            draw()
            onChange(v)
        }

        private fun draw() {
            for ((opt, b) in buttons) {
                val sel = opt == value
                b.background = round(if (sel) BLUE else SOFT, dp(context, 8).toFloat())
                b.setTextColor(if (sel) Color.WHITE else 0xFF1A1A1A.toInt())
            }
        }
    }
}
