#!/usr/bin/env python3
"""
Macro Recorder - record named keyboard + mouse macros (with time gaps)
and replay them one by one, in a loop.

Hotkeys (work even when the window is minimized):
    F9   start / stop recording
    F10  start / stop playback
    ESC  stop playback

Recordings are saved in a "recordings" folder next to this program.
Needs:  pip install pynput
"""

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

# Correct mouse positions on Windows with display scaling (125%, 150%...)
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

REC_HOTKEY = Key.f9
PLAY_HOTKEY = Key.f10
ABORT_KEY = Key.esc
MOVE_GAP = 0.01  # skip mouse moves closer together than this (seconds)

# folder next to the .exe (or next to the .py when run as a script)
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REC_DIR = os.path.join(BASE_DIR, "recordings")
PLAYLIST_FILE = os.path.join(REC_DIR, "_playlist.json")


# ------------------------------------------------------------ helpers
def key_to_data(key):
    if isinstance(key, Key):
        return {"special": key.name}
    if isinstance(key, KeyCode):
        if key.char is not None:
            return {"char": key.char}
        if key.vk is not None:
            return {"vk": key.vk}
    return None


def data_to_key(d):
    try:
        if "special" in d:
            return Key[d["special"]]
        if "char" in d:
            return KeyCode.from_char(d["char"])
        if "vk" in d:
            return KeyCode.from_vk(d["vk"])
    except Exception:
        pass
    return None


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "recording"


def fmt_secs(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------ app
class App:
    def __init__(self, root):
        self.root = root
        self.recs = []          # list of dicts: name, file, events, enabled
        self.state = "idle"     # idle | recording | playing
        self.events = []        # events of the recording in progress
        self.rec_name = ""
        self.rec_start = 0.0
        self.last_move = 0.0
        self.mouse_listener = None
        self.abort = threading.Event()
        self.injected = (None, 0.0)
        self.q = queue.Queue()

        os.makedirs(REC_DIR, exist_ok=True)
        self._build_ui()
        self._load_all()

        self.kb_listener = keyboard.Listener(on_press=self._on_press,
                                             on_release=self._on_release)
        self.kb_listener.daemon = True
        self.kb_listener.start()

        self.root.after(50, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================= UI
    def _build_ui(self):
        r = self.root
        r.title("Macro Recorder")
        r.attributes("-topmost", True)
        r.minsize(460, 460)

        main = ttk.Frame(r, padding=10)
        main.pack(fill="both", expand=True)

        # --- record row
        rec = ttk.LabelFrame(main, text="New recording", padding=8)
        rec.pack(fill="x")
        ttk.Label(rec, text="Name:").pack(side="left")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(rec, textvariable=self.name_var, width=24)
        self.name_entry.pack(side="left", padx=6, fill="x", expand=True)
        self.btn_rec = ttk.Button(rec, text="● Record (F9)", width=20,
                                  command=self.toggle_record)
        self.btn_rec.pack(side="left")

        # --- list of recordings
        lst = ttk.LabelFrame(main, text="Recordings  (tick ✔ = included in "
                                        "playback, played top to bottom)",
                             padding=8)
        lst.pack(fill="both", expand=True, pady=8)

        cols = ("play", "name", "length")
        self.tree = ttk.Treeview(lst, columns=cols, show="headings",
                                 height=9, selectmode="browse")
        self.tree.heading("play", text="Play")
        self.tree.heading("name", text="Name")
        self.tree.heading("length", text="Length")
        self.tree.column("play", width=45, anchor="center", stretch=False)
        self.tree.column("name", width=250)
        self.tree.column("length", width=70, anchor="center", stretch=False)
        sb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        lst.rowconfigure(0, weight=1)
        lst.columnconfigure(0, weight=1)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", lambda e: self.play_one())

        btns = ttk.Frame(lst)
        btns.grid(row=0, column=2, sticky="n", padx=(8, 0))
        for text, cmd in (("▲ Up", lambda: self.move(-1)),
                          ("▼ Down", lambda: self.move(1)),
                          ("Rename", self.rename),
                          ("Delete", self.delete),
                          ("Play only this", self.play_one),
                          ("Tick all", lambda: self.tick_all(True)),
                          ("Untick all", lambda: self.tick_all(False))):
            ttk.Button(btns, text=text, width=14, command=cmd
                       ).pack(pady=2, fill="x")

        # --- playback options
        opt = ttk.LabelFrame(main, text="Playback", padding=8)
        opt.pack(fill="x")

        def spin(row, col, label, var, frm, to, inc):
            ttk.Label(opt, text=label).grid(row=row, column=col, sticky="w",
                                            padx=(0, 4), pady=2)
            ttk.Spinbox(opt, from_=frm, to=to, increment=inc, width=7,
                        textvariable=var).grid(row=row, column=col + 1,
                                               sticky="w", padx=(0, 16))

        self.loops = tk.StringVar(value="0")
        self.gap = tk.StringVar(value="1")
        self.speed = tk.StringVar(value="1.0")
        self.delay = tk.StringVar(value="3")
        spin(0, 0, "Loops (0 = forever):", self.loops, 0, 99999, 1)
        spin(0, 2, "Speed (x):", self.speed, 0.25, 10, 0.25)
        spin(1, 0, "Gap between recordings (s):", self.gap, 0, 3600, 0.5)
        spin(1, 2, "Start delay (s):", self.delay, 0, 60, 1)

        self.minimize = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="Minimize window while recording / playing",
                        variable=self.minimize
                        ).grid(row=2, column=0, columnspan=4, sticky="w",
                               pady=(4, 0))

        self.btn_play = ttk.Button(main, text="▶ Play ticked in loop (F10)",
                                   command=self.toggle_play)
        self.btn_play.pack(fill="x", pady=(8, 2), ipady=4)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status, foreground="#0a5"
                  ).pack()
        ttk.Label(main, text="F9 record/stop · F10 play/stop · ESC stop",
                  foreground="#777").pack()

    def _refresh_tree(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, rec in enumerate(self.recs):
            ev = rec["events"]
            length = fmt_secs(ev[-1]["t"]) if ev else "0:00"
            self.tree.insert("", "end", iid=str(i), values=(
                "✔" if rec["enabled"] else "", rec["name"], length))
        if select is not None and 0 <= select < len(self.recs):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def _selected_index(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _on_tree_click(self, event):
        if self.tree.identify_column(event.x) == "#1":   # the Play column
            row = self.tree.identify_row(event.y)
            if row and self.state == "idle":
                rec = self.recs[int(row)]
                rec["enabled"] = not rec["enabled"]
                self._save_playlist()
                self._refresh_tree(select=int(row))
                return "break"

    # ================================================= storage
    def _load_all(self):
        self.recs = []
        found = {}
        for fn in os.listdir(REC_DIR):
            if fn.endswith(".json") and not fn.startswith("_"):
                try:
                    with open(os.path.join(REC_DIR, fn), encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):        # plain event list
                        data = {"name": fn[:-5], "events": data}
                    found[fn] = {"name": data.get("name", fn[:-5]),
                                 "file": fn,
                                 "events": data.get("events", []),
                                 "enabled": True}
                except Exception:
                    pass
        order, disabled = [], []
        try:
            with open(PLAYLIST_FILE, encoding="utf-8") as f:
                pl = json.load(f)
            order, disabled = pl.get("order", []), pl.get("disabled", [])
        except Exception:
            pass
        for fn in order:
            if fn in found:
                self.recs.append(found.pop(fn))
        self.recs += sorted(found.values(), key=lambda r: r["name"].lower())
        for r in self.recs:
            r["enabled"] = r["file"] not in disabled
        self._refresh_tree()
        self.status.set(f"{len(self.recs)} recording(s) loaded")

    def _save_playlist(self):
        try:
            with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
                json.dump({"order": [r["file"] for r in self.recs],
                           "disabled": [r["file"] for r in self.recs
                                        if not r["enabled"]]}, f, indent=1)
        except Exception as e:
            self.status.set(f"Could not save playlist: {e}")

    def _write_rec(self, rec):
        with open(os.path.join(REC_DIR, rec["file"]), "w",
                  encoding="utf-8") as f:
            json.dump({"name": rec["name"], "events": rec["events"]}, f)

    def _unique_default_name(self):
        names = {r["name"].lower() for r in self.recs}
        n = 1
        while f"recording {n}" in names:
            n += 1
        return f"Recording {n}"

    # ================================================= list actions
    def move(self, d):
        i = self._selected_index()
        if i is None or self.state != "idle":
            return
        j = i + d
        if 0 <= j < len(self.recs):
            self.recs[i], self.recs[j] = self.recs[j], self.recs[i]
            self._save_playlist()
            self._refresh_tree(select=j)

    def rename(self):
        i = self._selected_index()
        if i is None or self.state != "idle":
            return
        rec = self.recs[i]
        new = simpledialog.askstring("Rename", "New name:",
                                     initialvalue=rec["name"],
                                     parent=self.root)
        if not new or new.strip() == rec["name"]:
            return
        new = new.strip()
        new_file = safe_filename(new) + ".json"
        if any(r["file"].lower() == new_file.lower() for r in self.recs
               if r is not rec):
            messagebox.showerror("Rename", "A recording with that name exists.")
            return
        old_path = os.path.join(REC_DIR, rec["file"])
        rec["name"], rec["file"] = new, new_file
        self._write_rec(rec)
        if os.path.abspath(old_path) != os.path.abspath(
                os.path.join(REC_DIR, new_file)):
            try:
                os.remove(old_path)
            except OSError:
                pass
        self._save_playlist()
        self._refresh_tree(select=i)

    def delete(self):
        i = self._selected_index()
        if i is None or self.state != "idle":
            return
        rec = self.recs[i]
        if not messagebox.askyesno("Delete", f"Delete '{rec['name']}'?"):
            return
        try:
            os.remove(os.path.join(REC_DIR, rec["file"]))
        except OSError:
            pass
        del self.recs[i]
        self._save_playlist()
        self._refresh_tree(select=min(i, len(self.recs) - 1))

    def tick_all(self, value):
        if self.state != "idle":
            return
        for r in self.recs:
            r["enabled"] = value
        self._save_playlist()
        self._refresh_tree(select=self._selected_index())

    # ================================================= keyboard listener
    def _is_own_injection(self, key):
        k, t = self.injected
        return k == key and time.perf_counter() - t < 0.2

    def _on_press(self, key):
        if key == REC_HOTKEY:
            self.q.put(("hotkey_rec", None))
            return
        if key == PLAY_HOTKEY:
            self.q.put(("hotkey_play", None))
            return
        if self.state == "playing" and key == ABORT_KEY \
                and not self._is_own_injection(key):
            self.abort.set()
            return
        if self.state == "recording":
            d = key_to_data(key)
            if d:
                self._add({"type": "key_down", "key": d})

    def _on_release(self, key):
        if key in (REC_HOTKEY, PLAY_HOTKEY):
            return
        if self.state == "recording":
            d = key_to_data(key)
            if d:
                self._add({"type": "key_up", "key": d})

    def _poll(self):
        try:
            while True:
                msg, val = self.q.get_nowait()
                if msg == "hotkey_rec":
                    self.toggle_record(from_hotkey=True)
                elif msg == "hotkey_play":
                    self.toggle_play()
                elif msg == "status":
                    self.status.set(val)
                elif msg == "highlight":
                    self.tree.selection_set(str(val))
                    self.tree.see(str(val))
                elif msg == "play_done":
                    self._play_finished(val)
        except queue.Empty:
            pass
        if self.state == "recording":
            self.status.set(f"Recording '{self.rec_name}'... "
                            f"{len(self.events)} events  (F9 to stop)")
        self.root.after(50, self._poll)

    # ================================================= recording
    def _now(self):
        return round(time.perf_counter() - self.rec_start, 4)

    def _add(self, ev):
        ev["t"] = self._now()
        self.events.append(ev)

    def _on_move(self, x, y):
        if self.state != "recording":
            return
        t = self._now()
        if t - self.last_move >= MOVE_GAP:
            self.last_move = t
            self.events.append({"t": t, "type": "move", "x": x, "y": y})

    def _on_click(self, x, y, button, pressed):
        if self.state == "recording":
            self._add({"type": "click", "x": x, "y": y,
                       "button": button.name, "pressed": pressed})

    def _on_scroll(self, x, y, dx, dy):
        if self.state == "recording":
            self._add({"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy})

    def toggle_record(self, from_hotkey=False):
        if self.state == "playing":
            return
        if self.state == "recording":
            self.stop_record(from_button=not from_hotkey)
        elif self.state == "idle":
            self.start_record()

    def start_record(self):
        name = self.name_var.get().strip() or self._unique_default_name()
        fn = safe_filename(name) + ".json"
        if any(r["file"].lower() == fn.lower() for r in self.recs):
            if not messagebox.askyesno(
                    "Macro Recorder", f"'{name}' already exists. Replace it?"):
                return
        self.rec_name = name
        self.events = []
        self.state = "starting"
        if self.minimize.get():
            self.root.iconify()
        self.btn_rec.config(text="■ Stop recording (F9)")
        # short pause so the click on the Record button isn't recorded
        self.root.after(300, self._begin_record)

    def _begin_record(self):
        self.rec_start = time.perf_counter()
        self.last_move = 0.0
        self.state = "recording"
        self.mouse_listener = mouse.Listener(on_move=self._on_move,
                                             on_click=self._on_click,
                                             on_scroll=self._on_scroll)
        self.mouse_listener.daemon = True
        self.mouse_listener.start()

    def stop_record(self, from_button=False):
        self.state = "idle"
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        events = self.events
        if from_button:
            # drop the click on the Stop button
            for i in range(len(events) - 1, -1, -1):
                if events[i]["type"] == "click" and events[i]["pressed"]:
                    del events[i:]
                    break
        self.btn_rec.config(text="● Record (F9)")
        self.root.deiconify()

        fn = safe_filename(self.rec_name) + ".json"
        existing = next((i for i, r in enumerate(self.recs)
                         if r["file"].lower() == fn.lower()), None)
        rec = {"name": self.rec_name, "file": fn, "events": events,
               "enabled": True}
        if existing is not None:
            self.recs[existing] = rec
            idx = existing
        else:
            self.recs.append(rec)
            idx = len(self.recs) - 1
        try:
            self._write_rec(rec)
        except Exception as e:
            messagebox.showerror("Macro Recorder", f"Could not save:\n{e}")
        self._save_playlist()
        self._refresh_tree(select=idx)
        self.name_var.set("")
        length = events[-1]["t"] if events else 0
        self.status.set(f"Saved '{self.rec_name}' ({fmt_secs(length)})")

    # ================================================= playback
    def _read_options(self):
        try:
            return (max(0, int(float(self.loops.get()))),
                    max(0.0, float(self.gap.get())),
                    max(0.05, float(self.speed.get())),
                    max(0, int(float(self.delay.get()))))
        except ValueError:
            messagebox.showerror("Macro Recorder", "Check the playback numbers")
            return None

    def toggle_play(self):
        if self.state == "playing":
            self.abort.set()
        elif self.state == "idle":
            idxs = [i for i, r in enumerate(self.recs) if r["enabled"]]
            if not idxs:
                self.status.set("Tick ✔ at least one recording to play")
                return
            self._start_play(idxs, loop=True)

    def play_one(self):
        i = self._selected_index()
        if i is None or self.state != "idle":
            return
        self._start_play([i], loop=False)

    def _start_play(self, idxs, loop):
        opts = self._read_options()
        if opts is None:
            return
        loops, gap, speed, delay = opts
        if not loop:
            loops = 1
        playlist = [(i, self.recs[i]["name"], list(self.recs[i]["events"]))
                    for i in idxs]
        self.state = "playing"
        self.abort.clear()
        self.btn_play.config(text="■ Stop (F10 / ESC)")
        if self.minimize.get():
            self.root.iconify()
        threading.Thread(target=self._play_worker,
                         args=(playlist, loops, gap, speed, delay),
                         daemon=True).start()

    def _sleep(self, secs):
        """Sleep that wakes up immediately when stopped."""
        end = time.perf_counter() + secs
        while not self.abort.is_set():
            left = end - time.perf_counter()
            if left <= 0:
                return True
            time.sleep(min(left, 0.02))
        return False

    def _play_worker(self, playlist, loops, gap, speed, delay):
        kb = keyboard.Controller()
        ms = mouse.Controller()
        held_keys, held_buttons = set(), set()
        try:
            for s in range(delay, 0, -1):
                self.q.put(("status", f"Starting in {s}..."))
                if not self._sleep(1):
                    return
            loop = 0
            while loops == 0 or loop < loops:
                loop += 1
                total = "∞" if loops == 0 else loops
                for n, (idx, name, events) in enumerate(playlist, 1):
                    if self.abort.is_set():
                        return
                    self.q.put(("highlight", idx))
                    self.q.put(("status", f"Loop {loop}/{total} · "
                                f"'{name}' ({n}/{len(playlist)})  ESC stops"))
                    start = time.perf_counter()
                    for ev in events:
                        # wait for the event's original time -> keeps gaps
                        while True:
                            if self.abort.is_set():
                                return
                            left = ev["t"] / speed - (time.perf_counter()
                                                      - start)
                            if left <= 0:
                                break
                            time.sleep(min(left, 0.02))
                        self._do_event(ev, kb, ms, held_keys, held_buttons)
                    # release anything still held before the next recording
                    self._release_all(kb, ms, held_keys, held_buttons)
                    is_last = (n == len(playlist) and loops != 0
                               and loop == loops)
                    if gap > 0 and not is_last:
                        self.q.put(("status", f"Waiting {gap:g}s..."))
                        if not self._sleep(gap):
                            return
        except Exception as e:
            self.q.put(("status", f"Error: {e}"))
        finally:
            self._release_all(kb, ms, held_keys, held_buttons)
            self.q.put(("play_done", "Stopped" if self.abort.is_set()
                        else "Playback finished"))

    def _do_event(self, ev, kb, ms, held_keys, held_buttons):
        typ = ev["type"]
        if typ == "move":
            ms.position = (ev["x"], ev["y"])
        elif typ == "click":
            ms.position = (ev["x"], ev["y"])
            try:
                btn = Button[ev["button"]]
            except KeyError:
                return
            if ev["pressed"]:
                ms.press(btn)
                held_buttons.add(btn)
            else:
                ms.release(btn)
                held_buttons.discard(btn)
        elif typ == "scroll":
            ms.position = (ev["x"], ev["y"])
            ms.scroll(ev["dx"], ev["dy"])
        elif typ in ("key_down", "key_up"):
            key = data_to_key(ev["key"])
            if key is None:
                return
            self.injected = (key, time.perf_counter())
            if typ == "key_down":
                kb.press(key)
                held_keys.add(key)
            else:
                kb.release(key)
                held_keys.discard(key)

    @staticmethod
    def _release_all(kb, ms, held_keys, held_buttons):
        for k in list(held_keys):
            try:
                kb.release(k)
            except Exception:
                pass
        for b in list(held_buttons):
            try:
                ms.release(b)
            except Exception:
                pass
        held_keys.clear()
        held_buttons.clear()

    def _play_finished(self, text):
        self.state = "idle"
        self.btn_play.config(text="▶ Play ticked in loop (F10)")
        self.root.deiconify()
        self.status.set(text)

    def _on_close(self):
        if self.state == "recording":
            self.stop_record()
        self.abort.set()
        try:
            self.kb_listener.stop()
            if self.mouse_listener:
                self.mouse_listener.stop()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
