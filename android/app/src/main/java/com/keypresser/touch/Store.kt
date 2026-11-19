package com.keypresser.touch

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** All sequences are kept in one JSON file inside the app. */
object Store {
    private var file: File? = null
    var data: JSONObject = JSONObject()
        private set

    fun load(ctx: Context) {
        val f = File(ctx.filesDir, "keypresser.json")
        file = f
        data = try {
            if (f.exists()) JSONObject(f.readText()) else JSONObject()
        } catch (e: Exception) {
            JSONObject()
        }
        if (!data.has("seqs") || data.getJSONArray("seqs").length() == 0) {
            data.put("seqs", JSONArray().put(newSeq("Sequence 1")))
        }
        if (!data.has("cur")) data.put("cur", 0)
        if (!data.has("delay")) data.put("delay", 3)
    }

    fun save() {
        val f = file ?: return
        try {
            val tmp = File(f.path + ".tmp")
            tmp.writeText(data.toString(1))
            tmp.renameTo(f)
        } catch (_: Exception) {
        }
    }

    fun newSeq(name: String): JSONObject =
        JSONObject().put("name", name).put("loops", 1).put("steps", JSONArray())

    fun seqs(): JSONArray = data.getJSONArray("seqs")

    fun curIndex(): Int = data.optInt("cur", 0).coerceIn(0, seqs().length() - 1)

    fun cur(): JSONObject = seqs().getJSONObject(curIndex())

    fun steps(): JSONArray = cur().getJSONArray("steps")

    fun setCur(i: Int) { data.put("cur", i) }

    // ---- JSONArray helpers (JSONArray has no insert / move)
    fun list(a: JSONArray): MutableList<JSONObject> =
        MutableList(a.length()) { a.getJSONObject(it) }

    fun array(l: List<JSONObject>): JSONArray = JSONArray().also { a -> l.forEach { a.put(it) } }

    fun setSteps(l: List<JSONObject>) { cur().put("steps", array(l)) }

    fun copy(o: JSONObject): JSONObject = JSONObject(o.toString())
}
