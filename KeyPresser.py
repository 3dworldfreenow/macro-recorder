#!/usr/bin/env python3
"""
KeyPresser - presses a keyboard key again and again with a random gap,
clicks the mouse on screen points you choose, each point on its own random
timer (e.g. every 10-20 seconds), and opens links once or on a repeat timer.

F7 = add a click point at the current mouse position
F8 = start / stop      ESC = stop

Needs: pip install pynput
"""

import argparse
import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

from pynput import keyboard, mouse
from pynput.keyboard import Key
from pynput.mouse import Button

# correct coordinates on screens with 125% / 150% scaling
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "keypresser_settings.json")

KEYS = {
    "Right Arrow (next)": Key.right,
    "Left Arrow (back)": Key.left,
    "Down Arrow": Key.down,
    "Up Arrow": Key.up,
    "Enter": Key.enter,
    "Space": Key.space,
    "Page Down": Key.page_down,
    "Page Up": Key.page_up,
    "Tab": Key.tab,
    "N": "n",
}
CLICK_TYPES = ["Left", "Right", "Double"]


def screen_area(root):
    """Whole desktop (all monitors) as x, y, width, height."""
    if sys.platform == "win32":
        try:
            gm = ctypes.windll.user32.GetSystemMetrics
            w, h = gm(78), gm(79)
            if w > 0 and h > 0:
                return gm(76), gm(77), w, h
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def pick_on_screen(root, on_done, hide=()):
    """Dim the whole screen; the next tap/click gives its position.
    on_done(x, y) is called, or on_done(None, None) if cancelled."""
    for w in hide:
        w.withdraw()
    x0, y0, w, h = screen_area(root)
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.geometry(f"{w}x{h}+{x0}+{y0}")
    ov.attributes("-topmost", True)
    try:
        ov.attributes("-alpha", 0.3)
    except Exception:
        pass
    c = tk.Canvas(ov, bg="black", highlightthickness=0, cursor="crosshair")
    c.pack(fill="both", expand=True)

    # solid, easy-to-read banner on top of the dimmed screen
    ban = tk.Toplevel(root)
    ban.overrideredirect(True)
    ban.attributes("-topmost", True)
    ban.configure(bg="#1e3a5f")
    tk.Label(ban, text="Tap the spot you want clicked", bg="#1e3a5f",
             fg="white", font=("Segoe UI", 18, "bold")
             ).pack(padx=24, pady=(14, 4))
    tk.Label(ban, text="(anywhere on the dimmed screen)", bg="#1e3a5f",
             fg="#cfe0f5", font=("Segoe UI", 11)).pack()
    tk.Button(ban, text="CANCEL", bg="#c62828", fg="white", bd=0,
              activebackground="#e53935", font=("Segoe UI", 14, "bold"),
              padx=30, pady=6, command=lambda: finish(None, None)
              ).pack(pady=(10, 14))
    ban.update_idletasks()
    bw = ban.winfo_reqwidth()
    ban.geometry(f"+{(root.winfo_screenwidth() - bw) // 2}+40")

    def finish(x, y):
        for win in (ban, ov):
            try:
                win.destroy()
            except Exception:
                pass
        for win in hide:
            win.deiconify()
        on_done(x, y)

    def tapped(e):
        finish(e.x_root, e.y_root)

    c.bind("<ButtonPress-1>", tapped)
    ov.bind("<Escape>", lambda e: finish(None, None))
    def raise_banner():
        ov.focus_force()
        ban.attributes("-topmost", False)
        ban.attributes("-topmost", True)
        ban.lift(ov)

    ov.after(50, raise_banner)
    ov.after(400, raise_banner)
    return ov


class PointDialog(tk.Toplevel):
    """Add / edit one click point."""

    def __init__(self, parent, point):
        super().__init__(parent)
        self.title("Click point")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=12)
        f.pack()
        self.vars = {}
        rows = [("X:", "x"), ("Y:", "y"), ("Every from (sec):", "min"),
                ("to (sec):", "max")]
        for r, (label, k) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=str(point[k]))
            ttk.Entry(f, textvariable=v, width=10).grid(row=r, column=1,
                                                        sticky="w", pady=2)
            self.vars[k] = v
        ttk.Label(f, text="Click:").grid(row=4, column=0, sticky="w", pady=2)
        self.vars["click"] = tk.StringVar(value=point["click"])
        ttk.Combobox(f, textvariable=self.vars["click"], values=CLICK_TYPES,
                     state="readonly", width=8).grid(row=4, column=1,
                                                     sticky="w")
        ttk.Button(f, text="Pick on screen", command=self.pick
                   ).grid(row=0, column=2, rowspan=2, padx=(8, 0), sticky="ns")
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=3, pady=(10, 0))
        ttk.Button(b, text="OK", command=self.ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="left")
        self.parent = parent
        self.grab_set()
        self.wait_window()

    def pick(self):
        self.grab_release()

        def done(x, y):
            if x is not None:
                self.vars["x"].set(str(int(x)))
                self.vars["y"].set(str(int(y)))
            self.lift()
            self.grab_set()

        pick_on_screen(self.parent, done, hide=(self, self.parent))

    def ok(self):
        try:
            p = {"x": int(float(self.vars["x"].get())),
                 "y": int(float(self.vars["y"].get())),
                 "min": max(0.0, float(self.vars["min"].get())),
                 "max": max(0.0, float(self.vars["max"].get())),
                 "click": self.vars["click"].get()}
        except ValueError:
            messagebox.showerror("Click point", "Please enter numbers",
                                 parent=self)
            return
        if p["max"] < p["min"]:
            p["min"], p["max"] = p["max"], p["min"]
        self.result = p
        self.destroy()


class LinkDialog(tk.Toplevel):
    """Add / edit one link."""

    def __init__(self, parent, link):
        super().__init__(parent)
        self.title("Link")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="Link (URL):").grid(row=0, column=0, sticky="w")
        self.url = tk.StringVar(value=link["url"])
        e = ttk.Entry(f, textvariable=self.url, width=46)
        e.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, 8))
        e.focus_set()
        self.mode = tk.StringVar(value=link["mode"])
        ttk.Radiobutton(f, text="Open once (when you press Start)",
                        variable=self.mode, value="once"
                        ).grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Radiobutton(f, text="Repeat: open again every",
                        variable=self.mode, value="loop"
                        ).grid(row=3, column=0, sticky="w")
        self.min = tk.StringVar(value=str(link["min"]))
        self.max = tk.StringVar(value=str(link["max"]))
        ttk.Entry(f, textvariable=self.min, width=6).grid(row=3, column=1)
        ttk.Label(f, text="to").grid(row=3, column=2, padx=3)
        ttk.Entry(f, textvariable=self.max, width=6).grid(row=3, column=3)
        ttk.Label(f, text="seconds (random)").grid(row=4, column=1,
                                                  columnspan=3, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=4, pady=(10, 0))
        ttk.Button(b, text="OK", command=self.ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.ok())
        self.grab_set()
        self.wait_window()

    def ok(self):
        url = fix_url(self.url.get())
        if not url:
            messagebox.showerror("Link", "Please type a link", parent=self)
            return
        try:
            a = max(0.0, float(self.min.get()))
            b = max(0.0, float(self.max.get()))
        except ValueError:
            messagebox.showerror("Link", "Please enter numbers", parent=self)
            return
        a, b = min(a, b), max(a, b)
        if self.mode.get() == "loop" and b <= 0:
            messagebox.showerror("Link", "Repeat time must be more than 0",
                                 parent=self)
            return
        self.result = {"url": url, "mode": self.mode.get(), "min": a, "max": b}
        self.destroy()


def fix_url(url):
    url = (url or "").strip()
    if url and "://" not in url and not url.lower().startswith(
            ("mailto:", "file:")):
        url = "https://" + url
    return url


def open_link(url):
    try:
        if sys.platform == "win32":
            os.startfile(url)
        else:
            webbrowser.open(url, new=2)
    except Exception:
        webbrowser.open(url, new=2)


class App:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.kbc = keyboard.Controller()
        self.msc = mouse.Controller()
        self.sending = False
        self.points = []
        self.links = []
        self.logfile = open(args.log, "a", encoding="utf-8") if args.log else None

        s = self._load_settings()
        self._build_ui(s)

        if args.point:                       # points given on command line
            self.points = []
            for spec in args.point:
                x, y, a, b = (float(v) for v in spec.split(","))
                self.points.append({"x": int(x), "y": int(y), "min": a,
                                    "max": b, "click": "Left"})
        if args.link:                        # links given on command line
            self.links = []
            for spec in args.link:
                parts = spec.split("|")
                if len(parts) >= 3:
                    self.links.append({"url": fix_url(parts[0]), "mode": "loop",
                                       "min": float(parts[1]),
                                       "max": float(parts[2])})
                else:
                    self.links.append({"url": fix_url(parts[0]),
                                       "mode": "once", "min": 30, "max": 60})
        self._refresh_points()
        self._refresh_links()

        self.listener = keyboard.Listener(on_press=self._on_key)
        self.listener.daemon = True
        self.listener.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)
        root.after(100, self._track_mouse)
        if args.start:
            root.after(300, self.start)
        if args.open_picker:
            root.after(800, self.pick_point)

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        s = {}
        if not self.args.no_settings:
            try:
                with open(SETTINGS_FILE, encoding="utf-8") as f:
                    s = json.load(f)
            except Exception:
                s = {}
        self.points = s.get("points", [])
        self.links = s.get("links", [])
        return s

    def _save_settings(self):
        if self.args.no_settings:
            return
        data = {"key_on": self.key_on.get(), "key": self.key.get(),
                "kmin": self.kmin.get(), "kmax": self.kmax.get(),
                "limit": self.limit.get(), "delay": self.delay.get(),
                "pmin": self.pmin.get(), "pmax": self.pmax.get(),
                "restore": self.restore.get(), "points": self.points,
                "points_on": self.points_on.get(),
                "links_on": self.links_on.get(), "links": self.links}
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
        except Exception:
            pass

    # ------------------------------------------------------------ UI
    def _build_ui(self, s):
        a = self.args
        r = self.root
        r.title("KeyPresser")
        r.attributes("-topmost", True)
        r.minsize(480, 470)
        main = ttk.Frame(r, padding=10)
        main.pack(fill="both", expand=True)
        nb = ttk.Notebook(main)
        nb.pack(fill="both", expand=True)

        # --- keyboard tab
        kf = ttk.Frame(nb, padding=10)
        nb.add(kf, text=" Keyboard ")
        self.key_on = tk.BooleanVar(value=False if a.no_key
                                    else s.get("key_on", True))
        ttk.Checkbutton(kf, text="Press key:", variable=self.key_on
                        ).grid(row=0, column=0, sticky="w")
        key = a.key if a.key else s.get("key", "Right Arrow (next)")
        self.key = tk.StringVar(value=key if key in KEYS
                                else "Right Arrow (next)")
        ttk.Combobox(kf, textvariable=self.key, values=list(KEYS),
                     state="readonly", width=20
                     ).grid(row=0, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(kf, text="Random gap (sec):").grid(row=1, column=0,
                                                    sticky="w")
        self.kmin = tk.StringVar(value=str(a.min if a.min is not None
                                           else s.get("kmin", "0")))
        self.kmax = tk.StringVar(value=str(a.max if a.max is not None
                                           else s.get("kmax", "2")))
        ttk.Spinbox(kf, from_=0, to=600, increment=0.5, width=6,
                    textvariable=self.kmin).grid(row=1, column=1, sticky="w")
        ttk.Label(kf, text="to").grid(row=1, column=2, padx=4)
        ttk.Spinbox(kf, from_=0, to=600, increment=0.5, width=6,
                    textvariable=self.kmax).grid(row=1, column=3, sticky="w",
                                                 pady=2)
        ttk.Label(kf, text="Stop key after (0 = never):").grid(
            row=2, column=0, sticky="w")
        self.limit = tk.StringVar(value=str(a.limit if a.limit is not None
                                            else s.get("limit", "0")))
        ttk.Spinbox(kf, from_=0, to=999999, increment=1, width=8,
                    textvariable=self.limit).grid(row=2, column=1,
                                                  columnspan=2, sticky="w",
                                                  pady=2)

        # --- mouse points tab
        mf = ttk.Frame(nb, padding=10)
        nb.add(mf, text=" Mouse clicks ")
        self.points_on = tk.BooleanVar(value=s.get("points_on", True))
        ttk.Checkbutton(mf, text="Click these points (each on its own timer)",
                        variable=self.points_on
                        ).grid(row=0, column=0, columnspan=2, sticky="w",
                               pady=(0, 4))
        mf = ttk.Frame(mf)
        mf.grid(row=1, column=0, columnspan=2, sticky="nsew")
        mf.master.columnconfigure(0, weight=1)
        mf.master.rowconfigure(1, weight=1)
        cols = ("n", "x", "y", "click", "every")
        self.tree = ttk.Treeview(mf, columns=cols, show="headings", height=5)
        for c, t, w in (("n", "#", 30), ("x", "X", 60), ("y", "Y", 60),
                        ("click", "Click", 60), ("every", "Every (sec)", 100)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        self.tree.grid(row=0, column=0, rowspan=6, sticky="nsew")
        mf.columnconfigure(0, weight=1)
        mf.rowconfigure(4, weight=1)
        self.tree.bind("<Double-1>", lambda e: self.edit_point())
        for i, (t, cmd) in enumerate((("➕ Pick point", self.pick_point),
                                      ("Add at mouse (F7)", self.add_point_here),
                                      ("Edit", self.edit_point),
                                      ("Delete", self.delete_point),
                                      ("Test click", self.test_point))):
            ttk.Button(mf, text=t, width=17, command=cmd
                       ).grid(row=i, column=1, padx=(8, 0), pady=1, sticky="n")

        d = ttk.Frame(mf)
        d.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(d, text="New points: every").pack(side="left")
        self.pmin = tk.StringVar(value=str(s.get("pmin", "10")))
        self.pmax = tk.StringVar(value=str(s.get("pmax", "20")))
        ttk.Spinbox(d, from_=0, to=3600, increment=1, width=5,
                    textvariable=self.pmin).pack(side="left", padx=3)
        ttk.Label(d, text="to").pack(side="left")
        ttk.Spinbox(d, from_=0, to=3600, increment=1, width=5,
                    textvariable=self.pmax).pack(side="left", padx=3)
        ttk.Label(d, text="sec").pack(side="left")

        self.restore = tk.BooleanVar(value=s.get("restore", True))
        ttk.Checkbutton(mf, text="Put mouse back where it was after each click",
                        variable=self.restore
                        ).grid(row=7, column=0, columnspan=2, sticky="w")
        self.mouse_pos = tk.StringVar(value="Mouse now: -")
        ttk.Label(mf, textvariable=self.mouse_pos, foreground="#06c"
                  ).grid(row=8, column=0, columnspan=2, sticky="w",
                         pady=(4, 0))

        # --- links tab
        lf = ttk.Frame(nb, padding=10)
        nb.add(lf, text=" Open links ")
        self.links_on = tk.BooleanVar(value=s.get("links_on", True))
        ttk.Checkbutton(lf, text="Open these links in the browser",
                        variable=self.links_on
                        ).grid(row=0, column=0, columnspan=2, sticky="w",
                               pady=(0, 4))
        self.ltree = ttk.Treeview(lf, columns=("n", "url", "when"),
                                  show="headings", height=7)
        for c, t, w in (("n", "#", 30), ("url", "Link", 230),
                        ("when", "When", 110)):
            self.ltree.heading(c, text=t)
            self.ltree.column(c, width=w, anchor="w" if c == "url"
                              else "center")
        self.ltree.grid(row=1, column=0, rowspan=5, sticky="nsew")
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(5, weight=1)
        self.ltree.bind("<Double-1>", lambda e: self.edit_link())
        for i, (t, cmd) in enumerate((("Add", self.add_link),
                                      ("Edit", self.edit_link),
                                      ("Delete", self.delete_link),
                                      ("Test open", self.test_link))):
            ttk.Button(lf, text=t, width=11, command=cmd
                       ).grid(row=i + 1, column=1, padx=(8, 0), pady=1,
                              sticky="n")
        ttk.Label(lf, text="Once = opens one time when you press Start.\n"
                  "Repeat = opens at Start, then again on its random timer.\n"
                  "Each open makes a new browser tab.",
                  foreground="#777", justify="left"
                  ).grid(row=6, column=0, columnspan=2, sticky="w",
                         pady=(6, 0))

        if a.tab:
            nb.select({"keyboard": 0, "mouse": 1, "links": 2}.get(a.tab, 0))

        # --- start
        sf = ttk.Frame(main)
        sf.pack(fill="x", pady=(8, 0))
        ttk.Label(sf, text="Start delay (sec):").pack(side="left")
        self.delay = tk.StringVar(value=str(a.delay if a.delay is not None
                                            else s.get("delay", "3")))
        ttk.Spinbox(sf, from_=0, to=60, increment=1, width=5,
                    textvariable=self.delay).pack(side="left", padx=4)

        self.btn = ttk.Button(main, text="▶ Start (F8)", command=self.toggle)
        self.btn.pack(fill="x", pady=(8, 4), ipady=4)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status, foreground="#0a5").pack()
        self.count_var = tk.StringVar(
            value="Key presses: 0 · Clicks: 0 · Links opened: 0")
        ttk.Label(main, textvariable=self.count_var,
                  font=("Segoe UI", 11, "bold")).pack(pady=2)
        ttk.Label(main, text="Touch: tap Start / Stop · Keyboard: F7 add point, "
                  "F8 start/stop, ESC stop",
                  foreground="#777").pack()

    def _refresh_points(self):
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(self.points):
            self.tree.insert("", "end", iid=str(i), values=(
                i + 1, p["x"], p["y"], p["click"],
                f"{p['min']:g} - {p['max']:g}"))

    def _refresh_links(self):
        self.ltree.delete(*self.ltree.get_children())
        for i, l in enumerate(self.links):
            when = ("Once" if l["mode"] == "once"
                    else f"Every {l['min']:g}-{l['max']:g}s")
            self.ltree.insert("", "end", iid=str(i),
                              values=(i + 1, l["url"], when))

    def _lsel(self):
        s = self.ltree.selection()
        return int(s[0]) if s else None

    def add_link(self):
        if self.running():
            return
        d = LinkDialog(self.root, {"url": "", "mode": "once", "min": 30,
                                   "max": 60})
        if d.result:
            self.links.append(d.result)
            self._refresh_links()
            self._save_settings()

    def edit_link(self):
        i = self._lsel()
        if i is None or self.running():
            return
        d = LinkDialog(self.root, self.links[i])
        if d.result:
            self.links[i] = d.result
            self._refresh_links()
            self._save_settings()

    def delete_link(self):
        i = self._lsel()
        if i is None or self.running():
            return
        del self.links[i]
        self._refresh_links()
        self._save_settings()

    def test_link(self):
        i = self._lsel()
        if i is not None:
            open_link(self.links[i]["url"])

    def _track_mouse(self):
        try:
            x, y = self.msc.position
            self.mouse_pos.set(f"Mouse now: X {int(x)}, Y {int(y)}   "
                               "(press F7 to add this spot)")
        except Exception:
            pass
        self.root.after(100, self._track_mouse)

    # ------------------------------------------------------------ points
    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def pick_point(self):
        """Touch friendly: dim the screen and let the user tap the spot."""
        if self.running():
            return

        def done(x, y):
            if x is None:
                self.status.set("Pick cancelled")
            else:
                self.add_point_at(x, y)
            if self.args.quit_after_pick:
                self.close()

        pick_on_screen(self.root, done, hide=(self.root,))

    def add_point_here(self):
        if self.running():
            return
        x, y = self.msc.position
        self.add_point_at(x, y)

    def add_point_at(self, x, y):
        try:
            a, b = float(self.pmin.get()), float(self.pmax.get())
        except ValueError:
            a, b = 10.0, 20.0
        a, b = min(a, b), max(a, b)
        self.points.append({"x": int(x), "y": int(y), "min": a, "max": b,
                            "click": "Left"})
        self._refresh_points()
        self._save_settings()
        self.status.set(f"Added point {len(self.points)} at {int(x)}, {int(y)}")

    def edit_point(self):
        i = self._sel()
        if i is None or self.running():
            return
        d = PointDialog(self.root, self.points[i])
        if d.result:
            self.points[i] = d.result
            self._refresh_points()
            self._save_settings()

    def delete_point(self):
        i = self._sel()
        if i is None or self.running():
            return
        del self.points[i]
        self._refresh_points()
        self._save_settings()

    def test_point(self):
        i = self._sel()
        if i is None or self.running():
            return
        self.click_point(self.points[i], self.restore.get())

    def click_point(self, p, restore):
        old = self.msc.position
        self.msc.position = (p["x"], p["y"])
        time.sleep(0.05)
        if p["click"] == "Right":
            self.msc.click(Button.right, 1)
        elif p["click"] == "Double":
            self.msc.click(Button.left, 2)
        else:
            self.msc.click(Button.left, 1)
        if restore:
            time.sleep(0.05)
            self.msc.position = old

    # ------------------------------------------------------------ hotkeys
    def _on_key(self, key):
        if key == Key.f8:
            self.q.put(("toggle", None))
        elif key == Key.f7:
            self.q.put(("addpoint", None))
        elif key == Key.esc and not self.sending:
            self.q.put(("stop", None))

    # ------------------------------------------------------------ run
    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def toggle(self):
        if self.running():
            self.stop.set()
        else:
            self.start()

    def start(self):
        if self.running():
            return
        try:
            kmin, kmax = float(self.kmin.get()), float(self.kmax.get())
            limit = max(0, int(float(self.limit.get())))
            delay = max(0, int(float(self.delay.get())))
        except ValueError:
            self.status.set("Check the numbers")
            return
        kmin, kmax = max(0.0, min(kmin, kmax)), max(0.0, max(kmin, kmax))
        cfg = {"key_on": self.key_on.get(),
               "key": KEYS.get(self.key.get(), Key.right),
               "kmin": kmin, "kmax": kmax, "limit": limit, "delay": delay,
               "points": ([dict(p) for p in self.points]
                          if self.points_on.get() else []),
               "links": ([dict(l) for l in self.links]
                         if self.links_on.get() else []),
               "restore": self.restore.get(),
               "run_for": self.args.run_for}
        if not cfg["key_on"] and not cfg["points"] and not cfg["links"]:
            self.status.set("Turn on the key, or add a click point or link")
            return
        self._save_settings()
        self.stop.clear()
        self.worker = threading.Thread(target=self.work, args=(cfg,),
                                       daemon=True)
        self.worker.start()
        self.btn.config(text="■ Stop (F8 / ESC)")

    def wait_until(self, t):
        while not self.stop.is_set():
            left = t - time.perf_counter()
            if left <= 0:
                return True
            time.sleep(min(left, 0.01))
        return False

    def work(self, cfg):
        for s in range(cfg["delay"], 0, -1):
            self.q.put(("status", f"Starting in {s}... click your window"))
            if not self.wait_until(time.perf_counter() + 1):
                self.q.put(("finished", "Stopped"))
                return

        start = time.perf_counter()
        deadline = start + cfg["run_for"] if cfg["run_for"] else None
        tasks = []
        if cfg["key_on"]:
            tasks.append({"kind": "key", "next": start})
        for i, p in enumerate(cfg["points"]):
            tasks.append({"kind": "point", "i": i, "p": p,
                          "next": start + random.uniform(p["min"], p["max"])})
        for i, l in enumerate(cfg["links"]):
            tasks.append({"kind": "link", "i": i, "l": l, "next": start})
        nkeys = nclicks = nlinks = 0
        self.q.put(("status", "Running... (F8 / ESC to stop)"))

        while tasks and not self.stop.is_set():
            t = min(tasks, key=lambda x: x["next"])
            if deadline and t["next"] > deadline:
                self.wait_until(deadline)
                break
            if not self.wait_until(t["next"]):
                break
            if t["kind"] == "key":
                self.sending = True
                try:
                    self.kbc.press(cfg["key"])
                    time.sleep(0.03)
                    self.kbc.release(cfg["key"])
                finally:
                    time.sleep(0.02)
                    self.sending = False
                nkeys += 1
                self.q.put(("log", f"key {nkeys}"))
                if cfg["limit"] and nkeys >= cfg["limit"]:
                    tasks.remove(t)
                else:
                    t["next"] = time.perf_counter() + random.uniform(
                        cfg["kmin"], cfg["kmax"])
            elif t["kind"] == "link":
                l = t["l"]
                try:
                    open_link(l["url"])
                except Exception as e:
                    self.q.put(("status", f"Link error: {e}"))
                nlinks += 1
                self.q.put(("log", f"link {t['i'] + 1} {l['url']}"))
                if l["mode"] == "once":
                    tasks.remove(t)
                else:
                    t["next"] = time.perf_counter() + random.uniform(
                        l["min"], l["max"])
            else:
                p = t["p"]
                try:
                    self.click_point(p, cfg["restore"])
                except Exception as e:
                    self.q.put(("status", f"Click error: {e}"))
                nclicks += 1
                self.q.put(("log", f"click {t['i'] + 1} {p['x']} {p['y']}"))
                t["next"] = time.perf_counter() + random.uniform(p["min"],
                                                                 p["max"])
            self.q.put(("count", (nkeys, nclicks, nlinks)))

        done = f"{nkeys} key presses, {nclicks} clicks, {nlinks} links"
        msg = ("Stopped · " if self.stop.is_set() else "Done · ") + done
        self.q.put(("finished", msg))

    def poll(self):
        try:
            while True:
                msg, val = self.q.get_nowait()
                if msg == "toggle":
                    self.toggle()
                elif msg == "addpoint":
                    self.add_point_here()
                elif msg == "stop":
                    self.stop.set()
                elif msg == "status":
                    self.status.set(val)
                elif msg == "count":
                    self.count_var.set(f"Key presses: {val[0]} · "
                                       f"Clicks: {val[1]} · "
                                       f"Links opened: {val[2]}")
                elif msg == "log":
                    if self.logfile:
                        self.logfile.write(f"{time.time():.3f} {val}\n")
                        self.logfile.flush()
                elif msg == "finished":
                    self.status.set(val)
                    self.btn.config(text="▶ Start (F8)")
                    if self.args.quit_when_done:
                        self.close()
                        return
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def close(self):
        self.stop.set()
        self._save_settings()
        try:
            self.listener.stop()
        except Exception:
            pass
        if self.logfile:
            self.logfile.close()
            self.logfile = None
        self.root.destroy()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key", default=None)
    p.add_argument("--no-key", action="store_true")
    p.add_argument("--min", type=float, default=None)
    p.add_argument("--max", type=float, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--delay", type=int, default=None)
    p.add_argument("--point", action="append",
                   help="X,Y,MIN,MAX  (can repeat)")
    p.add_argument("--link", action="append",
                   help="URL (once) or URL|MIN|MAX (repeat); can repeat")
    p.add_argument("--open-picker", action="store_true")
    p.add_argument("--quit-after-pick", action="store_true")
    p.add_argument("--tab", default="", help="keyboard / mouse / links")
    p.add_argument("--run-for", type=float, default=0,
                   help="stop after this many seconds")
    p.add_argument("--start", action="store_true")
    p.add_argument("--quit-when-done", action="store_true")
    p.add_argument("--no-settings", action="store_true")
    p.add_argument("--log", default="")
    args, _ = p.parse_known_args()
    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
