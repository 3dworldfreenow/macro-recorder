package com.keypresser.touch

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.util.Base64
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class MainActivity : Activity() {

    companion object {
        var lastResult = ""
        var runner: Runner? = null
        const val REQ_STEP = 7
    }

    private lateinit var seqBtn: Button
    private lateinit var accBtn: Button
    private lateinit var ovBtn: Button
    private lateinit var permHint: TextView
    private lateinit var list: ListView
    private lateinit var adapter: ArrayAdapter<String>
    private lateinit var loopsEdit: EditText
    private lateinit var delayEdit: EditText
    private lateinit var resultView: TextView
    private val items = mutableListOf<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Store.load(this)
        buildUi()
        refresh()
        handleTestIntent(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (intent != null) handleTestIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        refreshPerms()
        resultView.text = lastResult
    }

    override fun onPause() {
        saveFields()
        super.onPause()
    }

    // ------------------------------------------------------------------ UI
    private fun buildUi() {
        val root = Ui.col(this)
        root.setBackgroundColor(Ui.BG)
        val p = Ui.dp(this, 12)
        root.setPadding(p, p, p, p)

        val top = Ui.row(this)
        top.addView(Ui.label(this, "KeyPresser", 20f, true, Ui.DARK))
        seqBtn = Ui.button(this, "", Ui.DARK, size = 15f) { seqDialog() }
        top.addView(Ui.weight(seqBtn, 1f, 6))
        root.addView(top)

        val perm = Ui.row(this)
        accBtn = Ui.button(this, "", Ui.RED, size = 13f) {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        ovBtn = Ui.button(this, "", Ui.RED, size = 13f) {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")))
        }
        perm.addView(Ui.weight(accBtn))
        perm.addView(Ui.weight(ovBtn))
        root.addView(perm)
        permHint = Ui.label(this, "", 12f, false, 0xFF6D4C41.toInt())
        permHint.setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:$packageName")))
        }
        root.addView(permHint)

        root.addView(Ui.label(this, "Steps run top to bottom, then repeat. Tap a step to change it.",
            13f, false, 0xFF555555.toInt()))
        list = ListView(this)
        adapter = object : ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, items) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
                val v = super.getView(position, convertView, parent) as TextView
                v.textSize = 15f
                v.setTextColor(0xFF1A1A1A.toInt())
                v.setPadding(Ui.dp(context, 10), Ui.dp(context, 12), Ui.dp(context, 10), Ui.dp(context, 12))
                return v
            }
        }
        list.adapter = adapter
        list.setBackgroundColor(0xFFFFFFFF.toInt())
        list.setOnItemClickListener { _, _, pos, _ -> stepMenu(pos) }
        root.addView(list, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        val add = Ui.row(this)
        add.addView(Ui.weight(Ui.button(this, "➕  Add step", Ui.GREEN) { editStep(-1) }, 2f))
        add.addView(Ui.weight(Ui.soft(this, "⋮ More") { moreMenu() }, 1f))
        root.addView(add)

        val opts = Ui.row(this)
        opts.addView(Ui.label(this, "Repeat ", 14f, true))
        loopsEdit = Ui.edit(this, "", "1", number = true)
        opts.addView(Ui.weight(loopsEdit, 1f))
        opts.addView(Ui.label(this, " times (0=∞)   Delay ", 13f))
        delayEdit = Ui.edit(this, Store.data.optInt("delay", 3).toString(), "3", number = true)
        opts.addView(Ui.weight(delayEdit, 1f))
        opts.addView(Ui.label(this, " s", 13f))
        root.addView(opts)

        root.addView(Ui.full(Ui.button(this, "▶  START", Ui.GREEN, size = 19f) { start() }, 8))
        resultView = Ui.label(this, "", 13f, false, Ui.GREEN)
        root.addView(resultView)
        setContentView(root)
    }

    private fun refresh() {
        val seq = Store.cur()
        seqBtn.text = "📂 ${seq.optString("name")}  (${Store.steps().length()})  ▾"
        items.clear()
        val steps = Store.steps()
        for (i in 0 until steps.length()) {
            val st = steps.getJSONObject(i)
            val nm = st.optString("name")
            val once = if (st.optString("run") == "once") "  [once]" else ""
            items.add("${i + 1}. " + (if (nm.isNotEmpty()) "$nm — " else "") + Steps.describe(st) +
                "$once   · then ${Steps.span(st.optDouble("amin", 0.0), st.optDouble("amax", 0.0))}s")
        }
        if (items.isEmpty()) items.add("No steps yet — tap ➕ Add step")
        adapter.notifyDataSetChanged()
        loopsEdit.setText(seq.optInt("loops", 1).toString())
    }

    private fun accessibilityOn(): Boolean {
        if (KPService.inst != null) return true
        val s = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
        return s?.contains("$packageName/") == true
    }

    private fun refreshPerms() {
        val acc = accessibilityOn()
        val ov = Overlay.canDraw(this)
        accBtn.text = if (acc) "✔ Accessibility ON" else "✖ Turn on Accessibility"
        accBtn.background = Ui.round(if (acc) Ui.GREEN else Ui.RED, Ui.dp(this, 10).toFloat())
        ovBtn.text = if (ov) "✔ Floating window ON" else "✖ Allow floating window"
        ovBtn.visibility = if (KPService.inst != null && !Overlay.canDraw(this)) View.GONE else View.VISIBLE
        ovBtn.background = Ui.round(if (ov) Ui.GREEN else Ui.RED, Ui.dp(this, 10).toFloat())
        permHint.text = if (acc) "" else
            "Tip: if Android says “Restricted setting”, tap here → ⋮ (top right) → " +
                "Allow restricted settings, then turn Accessibility on again."
        permHint.visibility = if (acc) View.GONE else View.VISIBLE
    }

    private fun saveFields() {
        if (!::loopsEdit.isInitialized) return
        Store.cur().put("loops", loopsEdit.text.toString().toIntOrNull() ?: 1)
        Store.data.put("delay", delayEdit.text.toString().toIntOrNull() ?: 3)
        Store.save()
    }

    // ------------------------------------------------------------------ steps
    private fun stepMenu(pos: Int) {
        if (pos >= Store.steps().length()) { editStep(-1); return }
        val opts = arrayOf("✏ Edit", "▲ Move up", "▼ Move down", "⧉ Copy", "🗑 Delete", "▶ Run only this step")
        AlertDialog.Builder(this).setTitle("Step ${pos + 1}").setItems(opts) { _, which ->
            val l = Store.list(Store.steps())
            when (which) {
                0 -> editStep(pos)
                1 -> if (pos > 0) { val t = l[pos]; l[pos] = l[pos - 1]; l[pos - 1] = t }
                2 -> if (pos < l.size - 1) { val t = l[pos]; l[pos] = l[pos + 1]; l[pos + 1] = t }
                3 -> l.add(pos + 1, Store.copy(l[pos]))
                4 -> l.removeAt(pos)
                5 -> {
                    val one = Store.copy(l[pos]).put("amin", 0).put("amax", 0)
                    runSeq(JSONObject().put("loops", 1).put("steps", JSONArray().put(one)), 2, null)
                    return@setItems
                }
            }
            if (which in 1..4) { Store.setSteps(l); Store.save(); refresh() }
        }.show()
    }

    private fun editStep(index: Int) {
        saveFields()
        val st = if (index >= 0) Store.steps().getJSONObject(index) else Steps.blank("app")
        val i = Intent(this, StepActivity::class.java)
        i.putExtra("step", st.toString())
        i.putExtra("index", index)
        @Suppress("DEPRECATION")
        startActivityForResult(i, REQ_STEP)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_STEP || resultCode != RESULT_OK || data == null) return
        val st = JSONObject(data.getStringExtra("step") ?: return)
        val index = data.getIntExtra("index", -1)
        val l = Store.list(Store.steps())
        if (index in l.indices) l[index] = st else l.add(st)
        Store.setSteps(l)
        Store.save()
        refresh()
    }

    // ------------------------------------------------------------------ sequences
    private fun seqDialog() {
        saveFields()
        val names = Store.list(Store.seqs()).mapIndexed { i, s ->
            (if (i == Store.curIndex()) "▶ " else "") + s.optString("name") + "  (${s.getJSONArray("steps").length()} steps)"
        }.toTypedArray()
        AlertDialog.Builder(this).setTitle("My sequences")
            .setItems(names) { _, i -> seqOptions(i) }
            .setPositiveButton("➕ New") { _, _ ->
                ask("New sequence", "Sequence ${Store.seqs().length() + 1}") { name ->
                    Store.seqs().put(Store.newSeq(name))
                    Store.setCur(Store.seqs().length() - 1)
                    Store.save(); refresh()
                }
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun seqOptions(i: Int) {
        val name = Store.seqs().getJSONObject(i).optString("name")
        AlertDialog.Builder(this).setTitle(name)
            .setItems(arrayOf("📂 Open", "✏ Rename", "⧉ Copy", "🗑 Delete")) { _, w ->
                val l = Store.list(Store.seqs())
                when (w) {
                    0 -> Store.setCur(i)
                    1 -> { ask("Rename", name) { nn -> l[i].put("name", nn); Store.save(); refresh() }; return@setItems }
                    2 -> l.add(i + 1, Store.copy(l[i]).put("name", "$name copy"))
                    3 -> if (l.size > 1) {
                        l.removeAt(i)
                        Store.setCur(0)
                    } else toast("You need at least one sequence")
                }
                if (w == 2 || w == 3) Store.data.put("seqs", Store.array(l))
                Store.save(); refresh()
            }.show()
    }

    private fun ask(title: String, value: String, ok: (String) -> Unit) {
        val e = Ui.edit(this, value)
        AlertDialog.Builder(this).setTitle(title).setView(e)
            .setPositiveButton("OK") { _, _ -> val t = e.text.toString().trim(); if (t.isNotEmpty()) ok(t) }
            .setNegativeButton("Cancel", null).show()
    }

    private fun moreMenu() {
        val opts = arrayOf("📋 Copy all sequences (to share / back up)", "📥 Paste sequences",
            "⚙ App info (permissions)")
        AlertDialog.Builder(this).setItems(opts) { _, w ->
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            when (w) {
                0 -> {
                    cm.setPrimaryClip(ClipData.newPlainText("KeyPresser sequences",
                        JSONObject().put("keypresser_sequences", 1).put("seqs", Store.seqs()).toString()))
                    toast("Copied ${Store.seqs().length()} sequences")
                }
                1 -> try {
                    val txt = cm.primaryClip?.getItemAt(0)?.text?.toString() ?: ""
                    val arr = JSONObject(txt).getJSONArray("seqs")
                    for (k in 0 until arr.length()) Store.seqs().put(arr.getJSONObject(k))
                    Store.save(); refresh()
                    toast("Pasted ${arr.length()} sequences")
                } catch (e: Exception) {
                    toast("Clipboard has no KeyPresser sequences")
                }
                2 -> startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:$packageName")))
            }
        }.show()
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    // ------------------------------------------------------------------ run
    private fun needsAccessibility(seq: JSONObject): Boolean {
        val steps = seq.optJSONArray("steps") ?: return false
        return (0 until steps.length()).any {
            steps.getJSONObject(it).optString("type") !in listOf("app", "link", "wait")
        }
    }

    private fun start() {
        saveFields()
        if (Store.steps().length() == 0) { toast("Add a step first"); return }
        runSeq(Store.copy(Store.cur()), delayEdit.text.toString().toIntOrNull() ?: 3, null)
    }

    private fun runSeq(seq: JSONObject, delay: Int, log: File?) {
        if (runner?.isAlive == true) { toast("Already running"); return }
        if (needsAccessibility(seq) && !accessibilityOn()) {
            toast("Turn on Accessibility for KeyPresser first")
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            return
        }
        val r = Runner(applicationContext, seq, delay, log)
        runner = r
        if (Overlay.canDraw(this)) {
            try {
                Overlay.showPanel(this, r)
                log?.appendText("0 panel shown\n")
            } catch (e: Exception) {
                log?.appendText("0 panel error ${e.javaClass.simpleName} ${e.message}\n")
                toast("Could not show the floating window: ${e.message}")
            }
        } else {
            log?.appendText("0 panel no-permission\n")
            toast("Tip: allow the floating window to see progress and Stop")
        }
        moveTaskToBack(true)
        r.start()
    }

    /** For automatic tests: adb shell am start ... --es kp_run_b64 <base64 json> */
    private fun handleTestIntent(i: Intent) {
        i.getStringExtra("kp_import_b64")?.let {
            i.removeExtra("kp_import_b64")
            val seq = JSONObject(String(Base64.decode(it, Base64.DEFAULT)))
            Store.seqs().put(seq)
            Store.setCur(Store.seqs().length() - 1)
            Store.save()
            refresh()
        }
        if (i.getBooleanExtra("kp_open_editor", false)) {
            i.removeExtra("kp_open_editor")
            editStep(i.getIntExtra("kp_editor_index", -1))
        }
        val b64 = i.getStringExtra("kp_run_b64") ?: return
        i.removeExtra("kp_run_b64")
        val seq = JSONObject(String(Base64.decode(b64, Base64.DEFAULT)))
        val log = if (i.getBooleanExtra("kp_log", false))
            File(filesDir, "run_log.txt") else null
        log?.delete()
        runSeq(seq, i.getIntExtra("kp_delay", 1), log)
    }
}
