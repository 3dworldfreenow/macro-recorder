package com.keypresser.touch

import android.app.Activity
import android.app.ActivityManager
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject

/** Add / edit one step (big, touch-friendly). */
class StepActivity : Activity() {

    private lateinit var st: JSONObject
    private var index = -1
    private lateinit var panel: LinearLayout
    private val collectors = mutableListOf<() -> Unit>()
    private lateinit var nameEdit: EditText
    private lateinit var runChoice: Ui.Choice
    private lateinit var aminEdit: EditText
    private lateinit var amaxEdit: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        st = JSONObject(intent.getStringExtra("step") ?: "{}")
        index = intent.getIntExtra("index", -1)
        if (!st.has("type")) st.put("type", "app")

        val outer = Ui.col(this)
        outer.setBackgroundColor(Ui.BG)
        val scroll = ScrollView(this)
        val body = Ui.col(this)
        val p = Ui.dp(this, 14)
        body.setPadding(p, p, p, p)
        scroll.addView(body)
        outer.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        body.addView(Ui.label(this, if (index < 0) "New step" else "Step ${index + 1}", 20f, true, Ui.DARK))
        body.addView(Ui.label(this, "Name (optional)", 14f, true))
        nameEdit = Ui.edit(this, st.optString("name"), "e.g. Open YouTube")
        body.addView(nameEdit)
        body.addView(Ui.label(this, "Runs", 14f, true))
        runChoice = Ui.Choice(this, listOf("Every loop", "Only once (first loop)"),
            if (st.optString("run") == "once") "Only once (first loop)" else "Every loop", 2)
        body.addView(runChoice)

        body.addView(Ui.label(this, "What should this step do?", 14f, true))
        val labels = Steps.TYPES.map { it.second }
        body.addView(Ui.Choice(this, labels, Steps.label(st.optString("type")), 3) { lbl ->
            collect()
            st.put("type", Steps.TYPES.first { it.second == lbl }.first)
            buildPanel()
        })

        panel = Ui.col(this)
        body.addView(panel)

        body.addView(Ui.label(this, "Then wait before next step (seconds, random)", 14f, true))
        val wr = Ui.row(this)
        aminEdit = Ui.edit(this, num(st.optDouble("amin", 1.0)), "from", number = true, decimal = true)
        amaxEdit = Ui.edit(this, num(st.optDouble("amax", 2.0)), "to", number = true, decimal = true)
        wr.addView(Ui.weight(aminEdit))
        wr.addView(Ui.label(this, "  to  "))
        wr.addView(Ui.weight(amaxEdit))
        body.addView(wr)

        val foot = Ui.row(this)
        val fp = Ui.dp(this, 10)
        foot.setPadding(fp, fp, fp, fp)
        foot.addView(Ui.weight(Ui.button(this, "✔  Save", Ui.GREEN, size = 18f) { save() }))
        foot.addView(Ui.weight(Ui.button(this, "Cancel", Ui.GREY, size = 18f) { finish() }))
        outer.addView(foot)
        setContentView(outer)
        buildPanel()
    }

    private fun num(v: Double): String =
        if (v == Math.floor(v)) v.toLong().toString() else v.toString()

    private fun d(e: EditText, def: Double = 0.0) = e.text.toString().toDoubleOrNull() ?: def
    private fun i(e: EditText, def: Int = 0) = e.text.toString().trim().toDoubleOrNull()?.toInt() ?: def

    private fun collect() {
        collectors.forEach { it() }
    }

    // ------------------------------------------------------------------ panels
    private fun buildPanel() {
        panel.removeAllViews()
        collectors.clear()
        when (st.optString("type")) {
            "app" -> appPanel()
            "link" -> linkPanel()
            "tap" -> tapPanel()
            "swipe" -> swipePanel()
            "wait" -> panel.addView(Ui.label(this,
                "This step only waits. Set the time in “Then wait” below.", 14f))
            "nav" -> navPanel()
            "text" -> textPanel()
            "find" -> findPanel()
            "read" -> readPanel()
        }
    }

    private fun appRow(title: String, keyPkg: String, keyLabel: String, allowNone: Boolean) {
        val lbl = Ui.label(this, "", 15f, true, Ui.BLUE)
        fun draw() {
            lbl.text = if (st.optString(keyPkg).isEmpty()) (if (allowNone) "Any app (Android decides)" else "No app chosen yet")
            else "${st.optString(keyLabel)}  ·  ${st.optString(keyPkg)}"
        }
        draw()
        panel.addView(Ui.full(Ui.button(this, title, Ui.BLUE) {
            chooseApp { pkg, label -> st.put(keyPkg, pkg).put(keyLabel, label); draw() }
        }))
        if (allowNone) panel.addView(Ui.full(Ui.soft(this, "Use any app") {
            st.put(keyPkg, "").put(keyLabel, ""); draw()
        }))
        panel.addView(lbl)
    }

    private fun appPanel() {
        panel.addView(Ui.label(this, "Opens an app on your phone.", 14f))
        appRow("📱  Choose app", "pkg", "app_label", false)
    }

    private fun linkPanel() {
        panel.addView(Ui.label(this, "Web address", 14f, true))
        val url = Ui.edit(this, st.optString("url"), "e.g. youtube.com/watch?v=…")
        panel.addView(url)
        panel.addView(Ui.label(this, "Open it in (optional): pick an app like YouTube or Chrome", 14f, true))
        appRow("📱  Choose app to open the link", "pkg", "app_label", true)
        collectors.add {
            var u = url.text.toString().trim()
            if (u.isNotEmpty() && !u.contains("://")) u = "https://$u"
            st.put("url", u)
        }
    }

    private fun xyRow(title: String, kx: String, ky: String): Pair<EditText, EditText> {
        val ex = Ui.edit(this, st.optInt(kx).toString(), "X", number = true)
        val ey = Ui.edit(this, st.optInt(ky).toString(), "Y", number = true)
        panel.addView(Ui.full(Ui.button(this, title, Ui.GREEN) {
            pickPoint(title) { x, y -> ex.setText(x.toString()); ey.setText(y.toString()) }
        }))
        val r = Ui.row(this)
        r.addView(Ui.label(this, "X "))
        r.addView(Ui.weight(ex))
        r.addView(Ui.label(this, "  Y "))
        r.addView(Ui.weight(ey))
        panel.addView(r)
        collectors.add { st.put(kx, i(ex)); st.put(ky, i(ey)) }
        return ex to ey
    }

    private fun repeatRows(what: String) {
        panel.addView(Ui.label(this, "How many times", 14f, true))
        val t = Ui.edit(this, st.optInt("times", 1).toString(), "1", number = true)
        panel.addView(t)
        panel.addView(Ui.label(this, "Gap between those $what (seconds)", 14f, true))
        val r = Ui.row(this)
        val a = Ui.edit(this, num(st.optDouble("tmin", 0.5)), "from", number = true, decimal = true)
        val b = Ui.edit(this, num(st.optDouble("tmax", 1.0)), "to", number = true, decimal = true)
        r.addView(Ui.weight(a)); r.addView(Ui.label(this, "  to  ")); r.addView(Ui.weight(b))
        panel.addView(r)
        collectors.add {
            st.put("times", maxOf(1, i(t, 1)))
            st.put("tmin", d(a, 0.5)); st.put("tmax", d(b, 1.0))
        }
    }

    private fun tapPanel() {
        xyRow("📍  Pick the spot on screen", "x", "y")
        panel.addView(Ui.label(this, "Kind of tap", 14f, true))
        val k = Ui.Choice(this, Steps.TAPS, st.optString("kind", "Tap"), 3)
        panel.addView(k)
        collectors.add { st.put("kind", k.value) }
        repeatRows("taps")
    }

    private fun swipePanel() {
        xyRow("📍  Pick where the swipe starts", "x", "y")
        xyRow("📍  Pick where the swipe ends", "x2", "y2")
        panel.addView(Ui.label(this, "Swipe speed (milliseconds, smaller = faster)", 14f, true))
        val ms = Ui.edit(this, st.optInt("ms", 400).toString(), "400", number = true)
        panel.addView(ms)
        collectors.add { st.put("ms", i(ms, 400)) }
        repeatRows("swipes")
    }

    private fun navPanel() {
        panel.addView(Ui.label(this, "Press", 14f, true))
        val c = Ui.Choice(this, Steps.NAV, st.optString("nav", "Back"), 2)
        panel.addView(c)
        collectors.add { st.put("nav", c.value) }
        repeatRows("presses")
    }

    private fun textPanel() {
        panel.addView(Ui.label(this, "Text to type", 14f, true))
        val t = Ui.edit(this, st.optString("text"), "Hello!", multi = true)
        panel.addView(t)
        panel.addView(Ui.label(this, "It types into the selected text box (or the first box on screen). " +
            "Tip: add a Tap or Find step before it to select the box.", 13f, false, 0xFF666666.toInt()))
        val ap = Ui.Choice(this, listOf("Replace the text", "Add to the text"),
            if (st.optBoolean("append")) "Add to the text" else "Replace the text", 2)
        panel.addView(ap)
        val en = Ui.Choice(this, listOf("No Enter", "Press Enter after"),
            if (st.optBoolean("enter")) "Press Enter after" else "No Enter", 2)
        panel.addView(en)
        collectors.add {
            st.put("text", t.text.toString())
            st.put("append", ap.value.startsWith("Add"))
            st.put("enter", en.value.startsWith("Press"))
        }
    }

    private fun actionRows(yesTitle: String, noTitle: String) {
        panel.addView(Ui.label(this, "Keep checking for up to (seconds, 0 = once)", 14f, true))
        val to = Ui.edit(this, num(st.optDouble("timeout", 0.0)), "0", number = true, decimal = true)
        panel.addView(to)
        for ((title, key, stepKey, def) in listOf(
            listOf(yesTitle, "on_yes", "yes_step", "Continue"),
            listOf(noTitle, "on_no", "no_step", "Stop"))) {
            panel.addView(Ui.label(this, title, 14f, true))
            val c = Ui.Choice(this, Steps.ACTIONS, st.optString(key, def), 2)
            panel.addView(c)
            val r = Ui.row(this)
            r.addView(Ui.label(this, "   step number (for Go to step): "))
            val se = Ui.edit(this, st.optInt(stepKey, 1).toString(), "1", number = true)
            r.addView(Ui.weight(se))
            panel.addView(r)
            collectors.add { st.put(key, c.value); st.put(stepKey, maxOf(1, i(se, 1))) }
        }
        collectors.add { st.put("timeout", d(to, 0.0)) }
    }

    private fun findPanel() {
        panel.addView(Ui.label(this, "Find this text / button and tap it", 14f, true))
        val kw = Ui.edit(this, st.optString("keyword"), "e.g. Back")
        panel.addView(kw)
        val m = Ui.Choice(this, Steps.MATCH, st.optString("mode", "Contains"), 3)
        panel.addView(m)
        panel.addView(Ui.label(this, "If there are several, tap", 14f, true))
        val w = Ui.Choice(this, Steps.WHICH, st.optString("which", "First"), 3)
        panel.addView(w)
        val nr = Ui.row(this)
        nr.addView(Ui.label(this, "   number (from the top): "))
        val ne = Ui.edit(this, st.optInt("n", 1).toString(), "1", number = true)
        nr.addView(Ui.weight(ne))
        panel.addView(nr)
        panel.addView(Ui.label(this, "Kind of tap", 14f, true))
        val k = Ui.Choice(this, Steps.TAPS, st.optString("kind", "Tap"), 3)
        panel.addView(k)
        panel.addView(Ui.label(this, "Tap a bit beside it (offset X / Y)", 14f, true))
        val orow = Ui.row(this)
        val dx = Ui.edit(this, st.optInt("dx").toString(), "0", number = true, signed = true)
        val dy = Ui.edit(this, st.optInt("dy").toString(), "0", number = true, signed = true)
        orow.addView(Ui.weight(dx)); orow.addView(Ui.weight(dy))
        panel.addView(orow)
        val test = Ui.label(this, "", 13f, false, Ui.BLUE)
        panel.addView(Ui.full(Ui.soft(this, "🔍 Test find now") {
            val s = KPService.inst
            if (s == null) { test.text = "Turn on Accessibility first"; return@soft }
            val hits = s.find(m.value, kw.text.toString())
            test.text = if (hits.isEmpty()) "Not found on this screen (it searches the screen behind this one when running)"
            else "Found ${hits.size}: " + hits.take(5).joinToString(" · ") { "“${it.text.take(25)}”" }
        }))
        panel.addView(test)
        collectors.add {
            st.put("keyword", kw.text.toString().trim()); st.put("mode", m.value)
            st.put("which", w.value); st.put("n", maxOf(1, i(ne, 1))); st.put("kind", k.value)
            st.put("dx", i(dx)); st.put("dy", i(dy))
        }
        actionRows("✔ If found (after tapping it)", "✖ If not found")
    }

    private fun readPanel() {
        panel.addView(Ui.label(this, "Checks the text on the screen", 14f, true))
        val m = Ui.Choice(this, Steps.READ_MATCH, st.optString("mode", "Contains"), 4)
        panel.addView(m)
        panel.addView(Ui.label(this, "Text / pattern (for Contains, Equals, Regex)", 14f, true))
        val pat = Ui.edit(this, st.optString("pattern"), "e.g. unread")
        panel.addView(pat)
        panel.addView(Ui.label(this, "For Number: the first number on screen must be", 14f, true))
        val op = Ui.Choice(this, Steps.OPS, st.optString("op", "="), 5)
        panel.addView(op)
        val nv = Ui.edit(this, num(st.optDouble("num", 0.0)), "0", number = true, decimal = true, signed = true)
        panel.addView(nv)
        collectors.add {
            st.put("mode", m.value); st.put("pattern", pat.text.toString())
            st.put("op", op.value); st.put("num", d(nv, 0.0))
        }
        actionRows("✔ If it matches", "✖ If not")
    }

    // ------------------------------------------------------------------ helpers
    private fun chooseApp(done: (String, String) -> Unit) {
        val pm = packageManager
        val apps = pm.queryIntentActivities(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.loadLabel(pm).toString() to it.activityInfo.packageName }
            .distinctBy { it.second }
            .sortedBy { it.first.lowercase() }
        val shown = apps.map { "${it.first}\n${it.second}" }.toMutableList()
        val box = Ui.col(this)
        val search = Ui.edit(this, "", "🔍 Search apps")
        box.addView(search)
        val lv = ListView(this)
        val ad = ArrayAdapter(this, android.R.layout.simple_list_item_1, shown)
        lv.adapter = ad
        box.addView(lv, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            Ui.dp(this, 400)))
        val dlg = AlertDialog.Builder(this).setTitle("Choose app").setView(box)
            .setNegativeButton("Cancel", null).create()
        search.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: Editable?) { ad.filter.filter(s) }
        })
        lv.setOnItemClickListener { _, _, pos, _ ->
            val item = ad.getItem(pos) ?: return@setOnItemClickListener
            val parts = item.split("\n")
            done(parts.last(), parts.first())
            dlg.dismiss()
        }
        dlg.show()
    }

    private fun pickPoint(prompt: String, done: (Int, Int) -> Unit) {
        if (!Overlay.canDraw(this)) {
            Toast.makeText(this, "Allow the floating window first", Toast.LENGTH_LONG).show()
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        moveTaskToBack(true)
        Overlay.pick(this, prompt, { x, y ->
            done(x, y)
            backToFront()
        }, { backToFront() })
    }

    private fun backToFront() {
        try {
            (getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).moveTaskToFront(taskId, 0)
        } catch (_: Exception) {
        }
    }

    private fun save() {
        collect()
        st.put("name", nameEdit.text.toString().trim())
        st.put("run", if (runChoice.value.startsWith("Only")) "once" else "every")
        val a = d(aminEdit, 0.0); val b = d(amaxEdit, 0.0)
        st.put("amin", minOf(a, b)); st.put("amax", maxOf(a, b))
        val err = when (st.optString("type")) {
            "app" -> if (st.optString("pkg").isEmpty()) "Choose an app" else null
            "link" -> if (st.optString("url").isEmpty()) "Type a web address" else null
            "find" -> if (st.optString("keyword").isEmpty()) "Type the text to find" else null
            else -> null
        }
        if (err != null) { Toast.makeText(this, err, Toast.LENGTH_LONG).show(); return }
        setResult(RESULT_OK, Intent().putExtra("step", st.toString()).putExtra("index", index))
        finish()
    }
}

