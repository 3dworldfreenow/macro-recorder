#!/usr/bin/env python3
"""
KeyPresser - touch-friendly Windows automation.

SEQUENCE tab: a list of steps run top to bottom, then repeated:
    - Mouse click at a point (once or many times)
    - Key press (once or many times)
    - Open a link
    - Wait
  Every step has its own random "then wait X-Y seconds" (0 is fine).

TIMER tabs (Key / Clicks / Links): things that repeat on their own random
timers at the same time.

Touch: everything works by tapping. While running, a small floating STOP
button is shown. Keyboard (optional): F7 add point at mouse, F8 start/stop,
ESC stop.

Needs: pip install pynput
"""

import argparse
import ctypes
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

from pynput import keyboard, mouse
from pynput.keyboard import Key
from pynput.mouse import Button

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

# name -> keys pressed together
KEYS = {
    "Right Arrow (next)": (Key.right,),
    "Left Arrow (back)": (Key.left,),
    "Down Arrow": (Key.down,),
    "Up Arrow": (Key.up,),
    "Enter": (Key.enter,),
    "Space": (Key.space,),
    "Page Down": (Key.page_down,),
    "Page Up": (Key.page_up,),
    "Tab": (Key.tab,),
    "F5 (refresh)": (Key.f5,),
    "Ctrl+W (close tab)": (Key.ctrl, "w"),
    "Ctrl+Tab (next tab)": (Key.ctrl, Key.tab),
    "Alt+Tab (switch app)": (Key.alt, Key.tab),
    "Home": (Key.home,),
    "End": (Key.end,),
    "N": ("n",),
}
CLICK_TYPES = ["Left", "Right", "Double"]

FONT = "Segoe UI"
SIZES = {"Small": 0.72, "Medium": 0.84, "Large": 1.0}
SCALE = SIZES["Medium"]


def sz(n):
    """Scale a size for the chosen UI size (Small / Medium / Large)."""
    return max(1, int(round(n * SCALE)))
GREEN, GREEN_A = "#2e7d32", "#388e3c"
RED, RED_A = "#c62828", "#e53935"
GREY = "#9e9e9e"
BLUE = "#1565c0"


# ====================================================================
# helpers
# ====================================================================
def fnum(v, default=0.0):
    try:
        return float(str(v).strip())
    except Exception:
        return default


def fmt(v):
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f"{v:g}"


def span(a, b):
    a, b = fnum(a), fnum(b)
    return fmt(a) if a == b else f"{fmt(a)}-{fmt(b)}"


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


def _guid(text):
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                    ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(text)
    g = GUID()
    g.d1, g.d2, g.d3 = u.fields[0], u.fields[1], u.fields[2]
    for i, b in enumerate(u.bytes[8:]):
        g.d4[i] = b
    return g


def _tabtip_toggle():
    """Ask the Windows touch keyboard to show/hide (ITipInvocation.Toggle).
    Returns True if it worked."""
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        clsid = _guid("4ce576fa-83dc-4f88-951c-9d0782b4e376")
        iid = _guid("37c994e7-432b-4834-a2f7-dce1f13b834b")
        ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 4,
                                    ctypes.byref(iid), ctypes.byref(ptr))
        if hr != 0 or not ptr.value:
            return False
        vt = ctypes.cast(ptr, ctypes.POINTER(
            ctypes.POINTER(ctypes.c_void_p)))[0]
        toggle = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                    ctypes.c_void_p)(vt[3])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
        hr = toggle(ptr, ctypes.windll.user32.GetDesktopWindow())
        release(ptr)
        return hr == 0
    except Exception:
        return False


def open_touch_keyboard():
    """Show Windows' on-screen keyboard (touch keyboard, else osk)."""
    if sys.platform != "win32":
        return
    if _tabtip_toggle():
        return
    tabtip = (r"C:\Program Files\Common Files\microsoft shared\ink"
              r"\TabTip.exe")
    try:
        if os.path.exists(tabtip):
            os.startfile(tabtip)
            time.sleep(0.6)
            if _tabtip_toggle():
                return
    except Exception:
        pass
    try:
        subprocess.Popen(["osk.exe"], shell=True)
    except Exception:
        pass


def keyboard_button(master, bg="#5e35b1", abg="#7e57c2", size=13):
    return tk.Button(master, text="⌨  Keyboard", command=open_touch_keyboard,
                     bg=bg, fg="white", activebackground=abg,
                     activeforeground="white", bd=0, relief="flat",
                     font=(FONT, sz(size), "bold"), padx=sz(16), pady=sz(8),
                     cursor="hand2", takefocus=0)


def screen_area(root):
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
    """Dim the screen; the next tap gives its position (or None if
    cancelled)."""
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

    ban = tk.Toplevel(root)
    ban.overrideredirect(True)
    ban.attributes("-topmost", True)
    ban.configure(bg="#1e3a5f")
    tk.Label(ban, text="Tap the spot you want clicked", bg="#1e3a5f",
             fg="white", font=(FONT, sz(18), "bold")).pack(padx=24, pady=(14, 4))
    tk.Label(ban, text="(anywhere on the dimmed screen)", bg="#1e3a5f",
             fg="#cfe0f5", font=(FONT, sz(11))).pack()
    tk.Button(ban, text="CANCEL", bg=RED, fg="white", bd=0,
              activebackground=RED_A, activeforeground="white",
              font=(FONT, sz(14), "bold"), padx=30, pady=6,
              command=lambda: finish(None, None)).pack(pady=(10, 14))
    ban.update_idletasks()
    ban.geometry(f"+{(root.winfo_screenwidth() - ban.winfo_reqwidth()) // 2}"
                 f"+40")

    def finish(x, y):
        for win in (ban, ov):
            try:
                win.destroy()
            except Exception:
                pass
        for win in hide:
            try:
                win.deiconify()
            except Exception:
                pass
        on_done(x, y)

    c.bind("<ButtonPress-1>", lambda e: finish(e.x_root, e.y_root))
    ov.bind("<Escape>", lambda e: finish(None, None))

    def raise_banner():
        try:
            ov.focus_force()
            ban.attributes("-topmost", False)
            ban.attributes("-topmost", True)
            ban.lift(ov)
        except Exception:
            pass

    ov.after(50, raise_banner)
    ov.after(400, raise_banner)


# ====================================================================
# touch widgets
# ====================================================================
def big_button(master, text, command, bg=BLUE, abg="#1976d2", size=13,
               padx=14, pady=10):
    return tk.Button(master, text=text, command=command, bg=bg, fg="white",
                     activebackground=abg, activeforeground="white", bd=0,
                     relief="flat", font=(FONT, sz(size), "bold"),
                     padx=sz(padx), pady=sz(pady), cursor="hand2")


def soft_button(master, text, command, size=12, padx=10, pady=9):
    return tk.Button(master, text=text, command=command, bg="#e3e8ef",
                     fg="#1a1a1a", activebackground="#cfd8e3", bd=0,
                     relief="flat", font=(FONT, sz(size), "bold"),
                     padx=sz(padx), pady=sz(pady), cursor="hand2")


class NumField(tk.Frame):
    """[ - ] [ 12 ] [ + ]  - easy to use with a finger."""

    def __init__(self, master, var, step=1.0, minv=0.0, maxv=999999.0,
                 width=5):
        super().__init__(master, bg=master["bg"] if "bg" in master.keys()
                         else "#f4f6f9")
        self.var, self.step, self.minv, self.maxv = var, step, minv, maxv
        soft_button(self, "−", lambda: self.add(-step), size=14, padx=12,
                    pady=2).pack(side="left")
        tk.Entry(self, textvariable=var, width=width, justify="center",
                 font=(FONT, sz(14)), relief="solid", bd=1
                 ).pack(side="left", padx=4, ipady=sz(6))
        soft_button(self, "+", lambda: self.add(step), size=14, padx=12,
                    pady=2).pack(side="left")

    def add(self, d):
        v = min(self.maxv, max(self.minv, fnum(self.var.get()) + d))
        self.var.set(fmt(v))


class Toggle(tk.Button):
    """Big on/off switch-button bound to a BooleanVar."""

    def __init__(self, master, text, var):
        super().__init__(master, command=self.flip, bd=0, relief="flat",
                         font=(FONT, sz(12), "bold"), padx=sz(14), pady=sz(8),
                         anchor="w", fg="white", activeforeground="white",
                         cursor="hand2")
        self.label, self.var = text, var
        var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def flip(self):
        self.var.set(not self.var.get())

    def draw(self):
        on = bool(self.var.get())
        self.config(text=("✔  ON   " if on else "✖  OFF  ") + self.label,
                    bg=GREEN if on else GREY,
                    activebackground=GREEN_A if on else "#bdbdbd")


class Choice(tk.Frame):
    """A row/grid of big buttons; one is selected (bound to a StringVar)."""

    def __init__(self, master, var, options, cols=3, size=12):
        super().__init__(master, bg=master["bg"] if "bg" in master.keys()
                         else "#f4f6f9")
        self.var, self.btns = var, {}
        for i, opt in enumerate(options):
            b = tk.Button(self, text=opt, bd=0, relief="flat",
                          font=(FONT, sz(size), "bold"), padx=sz(10),
                          pady=sz(9),
                          cursor="hand2",
                          command=lambda o=opt: self.var.set(o))
            b.grid(row=i // cols, column=i % cols, sticky="ew", padx=2,
                   pady=2)
            self.btns[opt] = b
        for c in range(cols):
            self.columnconfigure(c, weight=1, uniform="c")
        var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def draw(self):
        for opt, b in self.btns.items():
            sel = opt == self.var.get()
            b.config(bg=BLUE if sel else "#e3e8ef",
                     fg="white" if sel else "#1a1a1a",
                     activebackground="#1976d2" if sel else "#cfd8e3",
                     activeforeground="white" if sel else "#1a1a1a")


class Dialog(tk.Toplevel):
    """Base for big, touch-friendly dialogs."""

    BG = "#f4f6f9"

    def __init__(self, parent, title):
        super().__init__(parent)
        self.parent = parent
        self.title(title)
        self.configure(bg=self.BG)
        self.attributes("-topmost", True)
        self.result = None
        self.foot = tk.Frame(self, bg=self.BG, padx=16, pady=12)
        self.foot.pack(side="bottom", fill="x")    # OK/Cancel always visible
        topbar = tk.Frame(self, bg=self.BG, padx=16, pady=(8))
        topbar.pack(side="top", fill="x")
        keyboard_button(topbar, size=12).pack(side="right")
        # scrollable body (drag with a finger, scrollbar or mouse wheel)
        self.vsb = ttk.Scrollbar(self, orient="vertical")
        self.canvas = tk.Canvas(self, bg=self.BG, highlightthickness=0,
                                yscrollcommand=self.vsb.set)
        self.vsb.config(command=self.canvas.yview)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=self.BG, padx=16, pady=10)
        self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._resize)
        self.bind("<ButtonPress-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._motion, add="+")
        self.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(
            int(-e.delta / 120), "units"), add="+")
        self._y0, self._f0, self._drag = 0, 0.0, False

    def _resize(self, e=None):
        bw = self.body.winfo_reqwidth()
        bh = self.body.winfo_reqheight()
        avail = (self.winfo_screenheight() - 80
                 - self.foot.winfo_reqheight())
        ch = max(150, min(bh, avail))
        self.canvas.config(width=bw, height=ch, scrollregion=(0, 0, bw, bh))
        if bh > ch:
            if not self.vsb.winfo_ismapped():
                self.vsb.pack(side="right", fill="y", before=self.canvas)
        elif self.vsb.winfo_ismapped():
            self.vsb.pack_forget()
            self.canvas.yview_moveto(0)

    def _press(self, e):
        self._y0, self._f0, self._drag = (e.y_root, self.canvas.yview()[0],
                                          False)

    def _motion(self, e):
        dy = e.y_root - self._y0
        if self._drag or abs(dy) > 12:
            self._drag = True
            bh = max(1, self.body.winfo_reqheight())
            self.canvas.yview_moveto(max(0.0, self._f0 - dy / bh))

    def label(self, master, text, size=12, bold=True, fg="#1a1a1a"):
        return tk.Label(master, text=text, bg=self.BG, fg=fg, anchor="w",
                        justify="left",
                        font=(FONT, sz(size), "bold" if bold else "normal"))

    def footer(self):
        f = self.foot
        big_button(f, "✔  OK", self.ok, bg=GREEN, abg=GREEN_A, size=14,
                   pady=12).pack(side="left", fill="x", expand=True,
                                 padx=(0, 6))
        big_button(f, "Cancel", self.destroy, bg=GREY, abg="#bdbdbd",
                   size=14, pady=12).pack(side="left", fill="x",
                                          expand=True)

    def run(self):
        self.update_idletasks()
        self._resize()
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{max(0, (sw - w) // 2)}"
                      f"+{max(0, min((sh - h) // 3, sh - h - 60))}")
        self.grab_set()
        self.wait_window()
        if isinstance(self.parent, Dialog):      # back to the dialog below
            try:
                self.parent.grab_set()
                self.parent.lift()
            except Exception:
                pass
        return self.result

    def pick_into(self, xvar, yvar):
        self.grab_release()

        def done(x, y):
            if x is not None:
                xvar.set(str(int(x)))
                yvar.set(str(int(y)))
            self.lift()
            self.grab_set()

        pick_on_screen(self.parent, done, hide=(self, self.parent))

    def wait_row(self, master, amin, amax, text="Then wait (sec):"):
        r = tk.Frame(master, bg=self.BG)
        self.label(r, text).pack(anchor="w")
        rr = tk.Frame(r, bg=self.BG)
        rr.pack(anchor="w", pady=(2, 0))
        NumField(rr, amin, step=0.5).pack(side="left")
        self.label(rr, "  to  ", bold=False).pack(side="left")
        NumField(rr, amax, step=0.5).pack(side="left")
        return r

    def url_row(self, master, var):
        r = tk.Frame(master, bg=self.BG)
        self.label(r, "Link (web address):").pack(anchor="w")
        e = tk.Entry(r, textvariable=var, font=(FONT, sz(14)), relief="solid",
                     bd=1, width=34)
        e.pack(fill="x", ipady=sz(8), pady=(2, 6))
        b = tk.Frame(r, bg=self.BG)
        b.pack(fill="x")

        def paste():
            try:
                var.set(self.clipboard_get().strip())
            except Exception:
                pass

        soft_button(b, "📋 Paste", paste).pack(side="left", padx=(0, 6))
        soft_button(b, "⌨ Keyboard",
                    lambda: (e.focus_set(), open_touch_keyboard())
                    ).pack(side="left", padx=(0, 6))
        soft_button(b, "✖ Clear", lambda: var.set("")).pack(side="left")
        return r


class StepDialog(Dialog):
    """Add / edit one sequence step."""

    def __init__(self, parent, step):
        super().__init__(parent, "Step")
        s = dict(step)
        self.type = tk.StringVar(value={"click": "🖱 Click", "key": "⌨ Key",
                                        "link": "🔗 Link",
                                        "wait": "⏱ Wait"}[s.get("type",
                                                                "click")])
        self.x = tk.StringVar(value=str(s.get("x", 0)))
        self.y = tk.StringVar(value=str(s.get("y", 0)))
        self.btn = tk.StringVar(value=s.get("button", "Left"))
        self.key = tk.StringVar(value=s.get("key", "Right Arrow (next)"))
        self.times = tk.StringVar(value=fmt(s.get("times", 1)))
        self.tmin = tk.StringVar(value=fmt(s.get("tmin", 0.5)))
        self.tmax = tk.StringVar(value=fmt(s.get("tmax", 1)))
        self.url = tk.StringVar(value=s.get("url", ""))
        self.amin = tk.StringVar(value=fmt(s.get("amin", 0)))
        self.amax = tk.StringVar(value=fmt(s.get("amax", 2)))
        self.name = tk.StringVar(value=s.get("name", ""))
        self.run_mode = tk.StringVar(
            value="Only once (first loop)" if s.get("run") == "once"
            else "Every loop")

        b = self.body
        nr = tk.Frame(b, bg=self.BG)
        nr.pack(fill="x", pady=(0, 8))
        self.label(nr, "Name:  ").pack(side="left")
        ne = tk.Entry(nr, textvariable=self.name, font=(FONT, sz(14)),
                      relief="solid", bd=1)
        ne.pack(side="left", fill="x", expand=True, ipady=sz(6))
        soft_button(nr, "⌨", lambda: (ne.focus_set(), open_touch_keyboard()),
                    size=13, padx=12, pady=4).pack(side="left", padx=(6, 0))
        rr = tk.Frame(b, bg=self.BG)
        rr.pack(fill="x", pady=(0, 8))
        self.label(rr, "Runs:   ").pack(side="left")
        Choice(rr, self.run_mode, ["Every loop", "Only once (first loop)"],
               cols=2).pack(side="left", fill="x", expand=True)
        self.label(b, "What should this step do?").pack(anchor="w")
        Choice(b, self.type, ["🖱 Click", "⌨ Key", "🔗 Link", "⏱ Wait"],
               cols=4, size=13).pack(fill="x", pady=(4, 10))

        self.area = tk.Frame(b, bg=self.BG)
        self.area.pack(fill="both", expand=True)

        # --- click panel
        cp = self.click_panel = tk.Frame(self.area, bg=self.BG)
        big_button(cp, "📍  Pick the spot on screen",
                   lambda: self.pick_into(self.x, self.y), size=14,
                   pady=12).pack(fill="x")
        xy = tk.Frame(cp, bg=self.BG)
        xy.pack(anchor="w", pady=8)
        self.label(xy, "X ").pack(side="left")
        NumField(xy, self.x, step=1, maxv=99999).pack(side="left")
        self.label(xy, "   Y ").pack(side="left")
        NumField(xy, self.y, step=1, maxv=99999).pack(side="left")
        self.label(cp, "Click type:").pack(anchor="w")
        Choice(cp, self.btn, CLICK_TYPES, cols=3).pack(fill="x",
                                                       pady=(2, 8))

        # --- key panel
        kp = self.key_panel = tk.Frame(self.area, bg=self.BG)
        self.label(kp, "Key:").pack(anchor="w")
        Choice(kp, self.key, list(KEYS), cols=4, size=11).pack(fill="x",
                                                                pady=(2, 8))

        # --- repeat (click + key)
        rp = self.repeat_panel = tk.Frame(self.area, bg=self.BG)
        r1 = tk.Frame(rp, bg=self.BG)
        r1.pack(anchor="w")
        self.label(r1, "How many times:  ").pack(side="left")
        NumField(r1, self.times, step=1, minv=1).pack(side="left")
        self.wait_row(rp, self.tmin, self.tmax,
                      "Gap between those times (sec):").pack(anchor="w",
                                                             pady=(8, 0))

        # --- link panel
        lp = self.link_panel = tk.Frame(self.area, bg=self.BG)
        self.url_row(lp, self.url).pack(fill="x")

        # --- then wait (all)
        self.after_panel = self.wait_row(b, self.amin, self.amax,
                                         "Then wait before next step (sec):")
        self.after_panel.pack(anchor="w", pady=(12, 0))

        self.type.trace_add("write", lambda *a: self.show())
        self.show()
        self.footer()

    def kind(self):
        return {"🖱 Click": "click", "⌨ Key": "key", "🔗 Link": "link",
                "⏱ Wait": "wait"}[self.type.get()]

    def show(self):
        for p in (self.click_panel, self.key_panel, self.repeat_panel,
                  self.link_panel):
            p.pack_forget()
        k = self.kind()
        if k == "click":
            self.click_panel.pack(fill="x")
            self.repeat_panel.pack(fill="x")
        elif k == "key":
            self.key_panel.pack(fill="x")
            self.repeat_panel.pack(fill="x")
        elif k == "link":
            self.link_panel.pack(fill="x")

    def ok(self):
        k = self.kind()
        amin, amax = sorted((max(0, fnum(self.amin.get())),
                             max(0, fnum(self.amax.get()))))
        st = {"type": k, "amin": amin, "amax": amax,
              "name": self.name.get().strip(),
              "run": ("once" if self.run_mode.get().startswith("Only")
                      else "every")}
        if k in ("click", "key"):
            tmin, tmax = sorted((max(0, fnum(self.tmin.get())),
                                 max(0, fnum(self.tmax.get()))))
            st.update(times=max(1, int(fnum(self.times.get(), 1))),
                      tmin=tmin, tmax=tmax)
        if k == "click":
            st.update(x=int(fnum(self.x.get())), y=int(fnum(self.y.get())),
                      button=self.btn.get())
        elif k == "key":
            st["key"] = self.key.get()
        elif k == "link":
            url = fix_url(self.url.get())
            if not url:
                messagebox.showerror("Step", "Please enter a link",
                                     parent=self)
                return
            st["url"] = url
        self.result = st
        self.destroy()


class PointDialog(Dialog):
    def __init__(self, parent, p):
        super().__init__(parent, "Click point")
        self.x = tk.StringVar(value=str(p["x"]))
        self.y = tk.StringVar(value=str(p["y"]))
        self.btn = tk.StringVar(value=p.get("click", "Left"))
        self.min = tk.StringVar(value=fmt(p["min"]))
        self.max = tk.StringVar(value=fmt(p["max"]))
        b = self.body
        big_button(b, "📍  Pick the spot on screen",
                   lambda: self.pick_into(self.x, self.y), size=14,
                   pady=12).pack(fill="x")
        xy = tk.Frame(b, bg=self.BG)
        xy.pack(anchor="w", pady=8)
        self.label(xy, "X ").pack(side="left")
        NumField(xy, self.x, maxv=99999).pack(side="left")
        self.label(xy, "   Y ").pack(side="left")
        NumField(xy, self.y, maxv=99999).pack(side="left")
        self.label(b, "Click type:").pack(anchor="w")
        Choice(b, self.btn, CLICK_TYPES).pack(fill="x", pady=(2, 8))
        self.wait_row(b, self.min, self.max, "Click every (sec, random):"
                      ).pack(anchor="w")
        self.footer()

    def ok(self):
        a, c = sorted((max(0, fnum(self.min.get())),
                       max(0, fnum(self.max.get()))))
        self.result = {"x": int(fnum(self.x.get())),
                       "y": int(fnum(self.y.get())), "min": a, "max": c,
                       "click": self.btn.get()}
        self.destroy()


class LinkDialog(Dialog):
    def __init__(self, parent, l):
        super().__init__(parent, "Link")
        self.url = tk.StringVar(value=l["url"])
        self.mode = tk.StringVar(value="Open once" if l["mode"] == "once"
                                 else "Repeat")
        self.min = tk.StringVar(value=fmt(l["min"]))
        self.max = tk.StringVar(value=fmt(l["max"]))
        b = self.body
        self.url_row(b, self.url).pack(fill="x")
        self.label(b, "When:").pack(anchor="w", pady=(10, 0))
        Choice(b, self.mode, ["Open once", "Repeat"], cols=2
               ).pack(fill="x", pady=(2, 8))
        self.rep = self.wait_row(b, self.min, self.max,
                                 "Repeat every (sec, random):")
        self.mode.trace_add("write", lambda *a: self.show())
        self.show()
        self.footer()

    def show(self):
        if self.mode.get() == "Repeat":
            self.rep.pack(anchor="w")
        else:
            self.rep.pack_forget()

    def ok(self):
        url = fix_url(self.url.get())
        if not url:
            messagebox.showerror("Link", "Please enter a link", parent=self)
            return
        a, c = sorted((max(0, fnum(self.min.get())),
                       max(0, fnum(self.max.get()))))
        loop = self.mode.get() == "Repeat"
        if loop and c <= 0:
            messagebox.showerror("Link", "Repeat time must be more than 0",
                                 parent=self)
            return
        self.result = {"url": url, "mode": "loop" if loop else "once",
                       "min": a, "max": c}
        self.destroy()


class NameDialog(Dialog):
    def __init__(self, parent, title, value=""):
        super().__init__(parent, title)
        self.var = tk.StringVar(value=value)
        self.label(self.body, "Name:").pack(anchor="w")
        r = tk.Frame(self.body, bg=self.BG)
        r.pack(fill="x", pady=(2, 4))
        e = tk.Entry(r, textvariable=self.var, font=(FONT, sz(15)),
                     relief="solid", bd=1, width=26)
        e.pack(side="left", fill="x", expand=True, ipady=sz(8))
        soft_button(r, "⌨", lambda: (e.focus_set(), open_touch_keyboard()),
                    size=13, padx=12, pady=6).pack(side="left", padx=(6, 0))
        e.focus_set()
        e.select_range(0, "end")
        self.bind("<Return>", lambda ev: self.ok())
        self.footer()

    def ok(self):
        v = self.var.get().strip()
        if not v:
            messagebox.showerror("Name", "Please type a name", parent=self)
            return
        self.result = v
        self.destroy()


class SeqListDialog(Dialog):
    """List of all sequences: open, new, rename, copy, delete, reorder."""

    def __init__(self, app):
        super().__init__(app.root, "My sequences")
        self.app = app
        self.label(self.body, "Tap a sequence, then tap Open.",
                   bold=False, fg="#555").pack(anchor="w")
        fr = tk.Frame(self.body, bg=self.BG)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv = ttk.Treeview(fr, columns=("n", "name", "steps", "rep"),
                               show="headings", height=7,
                               selectmode="browse")
        for c, t, w, a in (("n", "#", 40, "center"),
                           ("name", "Name", 260, "w"),
                           ("steps", "Steps", 80, "center"),
                           ("rep", "Repeat", 100, "center")):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=sz(w), anchor=a)
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Double-1>", lambda e: self.ok())
        g = tk.Frame(self.body, bg=self.BG)
        g.pack(fill="x")
        for i, (t, cmd) in enumerate((("➕ New", self.new),
                                      ("✏ Rename", self.rename),
                                      ("⧉ Copy", self.copy),
                                      ("🗑 Delete", self.delete),
                                      ("▲ Up", lambda: self.move(-1)),
                                      ("▼ Down", lambda: self.move(1)))):
            soft_button(g, t, cmd).grid(row=i // 3, column=i % 3,
                                        sticky="ew", padx=3, pady=3)
        for c in range(3):
            g.columnconfigure(c, weight=1, uniform="b")
        self.refresh(app.cur)
        self.footer()
        self.ok_btn.config(text="✔  Open")

    def footer(self):
        super().footer()
        self.ok_btn = self.foot.winfo_children()[0]

    def sel(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def refresh(self, select=None):
        self.app._sync_loops()
        self.tv.delete(*self.tv.get_children())
        for i, sq in enumerate(self.app.seqs):
            lp = int(fnum(sq.get("loops", 0)))
            self.tv.insert("", "end", iid=str(i), values=(
                i + 1, ("▶ " if i == self.app.cur else "") + sq["name"],
                len(sq["steps"]), "forever" if lp == 0 else f"{lp} times"))
        if select is not None and 0 <= select < len(self.app.seqs):
            self.tv.selection_set(str(select))
            self.tv.see(str(select))

    def unique(self, name):
        names = {s["name"].lower() for s in self.app.seqs}
        if name.lower() not in names:
            return name
        n = 2
        while f"{name} ({n})".lower() in names:
            n += 1
        return f"{name} ({n})"

    def new(self):
        name = NameDialog(self, "New sequence",
                          self.unique(f"Sequence {len(self.app.seqs) + 1}")
                          ).run()
        if name:
            self.app.seqs.append({"name": self.unique(name), "loops": "0",
                                  "steps": []})
            self.app._save_settings()
            self.refresh(len(self.app.seqs) - 1)

    def rename(self):
        i = self.sel()
        if i is None:
            return
        name = NameDialog(self, "Rename sequence",
                          self.app.seqs[i]["name"]).run()
        if name:
            self.app.seqs[i]["name"] = name
            self.app._save_settings()
            self.app._update_seq_btn()
            self.refresh(i)

    def copy(self):
        i = self.sel()
        if i is None:
            return
        src = self.app.seqs[i]
        self.app.seqs.insert(i + 1, {
            "name": self.unique(src["name"] + " copy"),
            "loops": src.get("loops", "0"),
            "steps": [dict(st) for st in src["steps"]]})
        if self.app.cur > i:
            self.app.cur += 1
        self.app._save_settings()
        self.refresh(i + 1)

    def delete(self):
        i = self.sel()
        if i is None:
            return
        if len(self.app.seqs) == 1:
            messagebox.showinfo("Delete", "You need at least one sequence.",
                                parent=self)
            return
        if not messagebox.askyesno(
                "Delete", f"Delete '{self.app.seqs[i]['name']}'?",
                parent=self):
            return
        del self.app.seqs[i]
        if self.app.cur == i:
            self.app.cur = -1
            self.app.switch_seq(min(i, len(self.app.seqs) - 1))
        elif self.app.cur > i:
            self.app.cur -= 1
        self.app._save_settings()
        self.refresh(min(i, len(self.app.seqs) - 1))

    def move(self, d):
        i = self.sel()
        if i is None:
            return
        j = i + d
        seqs = self.app.seqs
        if 0 <= j < len(seqs):
            seqs[i], seqs[j] = seqs[j], seqs[i]
            if self.app.cur == i:
                self.app.cur = j
            elif self.app.cur == j:
                self.app.cur = i
            self.app._save_settings()
            self.refresh(j)

    def ok(self):
        i = self.sel()
        self.result = i if i is not None else self.app.cur
        self.destroy()


class KeyChooser(Dialog):
    def __init__(self, parent, current):
        super().__init__(parent, "Choose key")
        self.var = tk.StringVar(value=current)
        self.label(self.body, "Tap a key:").pack(anchor="w")
        Choice(self.body, self.var, list(KEYS), cols=3, size=12
               ).pack(fill="x", pady=4)
        self.footer()

    def ok(self):
        self.result = self.var.get()
        self.destroy()


def describe(st):
    t = st.get("type")
    if t == "click":
        d = f"🖱 {st.get('button', 'Left')} click  ({st['x']}, {st['y']})"
    elif t == "key":
        d = f"⌨ {st.get('key')}"
    elif t == "link":
        d = f"🔗 {st.get('url')}"
    else:
        return "⏱ Wait"
    n = int(st.get("times", 1))
    if t in ("click", "key") and n > 1:
        d += f"  × {n}  (gap {span(st.get('tmin', 0), st.get('tmax', 0))}s)"
    return d


# ====================================================================
# the app
# ====================================================================
class App:
    BG = "#f4f6f9"

    def __init__(self, root, args):
        self.root, self.args = root, args
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.kbc = keyboard.Controller()
        self.msc = mouse.Controller()
        self.sending = False
        self.mini = None
        self.mini_rect = None
        self.logfile = open(args.log, "a", encoding="utf-8") if args.log else None

        s = self._load_settings()
        global SCALE
        self.ui_size = s.get("ui_size", "Medium")
        if self.args.ui_size:
            self.ui_size = self.args.ui_size
        SCALE = SIZES.get(self.ui_size, SIZES["Medium"])
        self._style()
        self._build_ui(s)
        self._apply_cli()
        self._refresh_all()

        self.listener = keyboard.Listener(on_press=self._on_key)
        self.listener.daemon = True
        self.listener.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)
        root.after(150, self._track_mouse)
        if args.start:
            root.after(400, self.start)
        if args.open_picker:
            root.after(800, self.pick_point)
        if args.show_keyboard:
            root.after(1500, open_touch_keyboard)
        if args.open_seq_list:
            root.after(800, self.open_seq_list)
        if args.open_step_editor is not None:
            root.after(800, lambda: self.edit_step(args.open_step_editor))

    # ---------------------------------------------------------- settings
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
        seqs = s.get("seqs")
        if not seqs:                       # older settings: one sequence
            seqs = [{"name": "Sequence 1", "loops": str(s.get("loops", "0")),
                     "steps": s.get("steps", [])}]
        self.seqs = seqs
        self.cur = min(max(0, int(fnum(s.get("cur", 0)))), len(seqs) - 1)
        self.steps = self.seqs[self.cur]["steps"]
        return s

    def _state(self):
        return {"key_on": self.key_on.get(), "key": self.key.get(),
                "kmin": self.kmin.get(), "kmax": self.kmax.get(),
                "limit": self.limit.get(), "delay": self.delay.get(),
                "pmin": self.pmin.get(), "pmax": self.pmax.get(),
                "restore": self.restore.get(), "points": self.points,
                "points_on": self.points_on.get(),
                "links_on": self.links_on.get(), "links": self.links,
                "seqs": self._sync_loops(), "cur": self.cur,
                "hide": self.hide.get(), "ui_size": self.ui_size}

    def _save_settings(self):
        if self.args.no_settings:
            return
        data = self._state()
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
        except Exception:
            pass

    def _apply_cli(self):
        a = self.args
        if a.point:
            self.points = []
            for spec in a.point:
                x, y, mn, mx = (float(v) for v in spec.split(","))
                self.points.append({"x": int(x), "y": int(y), "min": mn,
                                    "max": mx, "click": "Left"})
        if a.link:
            self.links = []
            for spec in a.link:
                parts = spec.split("|")
                if len(parts) >= 3:
                    self.links.append({"url": fix_url(parts[0]),
                                       "mode": "loop",
                                       "min": float(parts[1]),
                                       "max": float(parts[2])})
                else:
                    self.links.append({"url": fix_url(parts[0]),
                                       "mode": "once", "min": 30, "max": 60})
        if a.seq_file:
            with open(a.seq_file, encoding="utf-8") as f:
                d = json.load(f)
            if "seqs" in d:
                self.seqs = d["seqs"]
            else:
                self.seqs = [{"name": d.get("name", "Test"),
                              "loops": str(d.get("loops", 0)),
                              "steps": d.get("steps", [])}]
            self.cur = -1
            self.switch_seq(0, save=False)
        if a.seq:
            for i, sq in enumerate(self.seqs):
                if sq["name"].lower() == a.seq.lower():
                    self.switch_seq(i, save=False)
        if a.tab:
            self.nb.select({"sequence": 0, "keyboard": 1, "key": 1,
                            "mouse": 2, "clicks": 2,
                            "links": 3}.get(a.tab, 0))

    # ---------------------------------------------------------- UI
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", font=(FONT, sz(12)), background=self.BG)
        st.configure("TFrame", background=self.BG)
        st.configure("TNotebook", background=self.BG, borderwidth=0)
        st.configure("TNotebook.Tab", font=(FONT, sz(13), "bold"),
                     padding=(sz(18), sz(10)))
        st.map("TNotebook.Tab", background=[("selected", "white")])
        st.configure("Treeview", rowheight=sz(46), font=(FONT, sz(12)),
                     fieldbackground="white")
        st.configure("Treeview.Heading", font=(FONT, sz(11), "bold"),
                     padding=6)
        st.map("Treeview", background=[("selected", "#bbdefb")],
               foreground=[("selected", "#000")])
        st.configure("Vertical.TScrollbar", arrowsize=sz(30))

    def _lbl(self, master, text, size=12, bold=False, fg="#1a1a1a"):
        return tk.Label(master, text=text, bg=self.BG, fg=fg,
                        font=(FONT, sz(size), "bold" if bold else "normal"),
                        anchor="w", justify="left")

    def _tree(self, master, cols, height=6):
        fr = tk.Frame(master, bg=self.BG)
        tv = ttk.Treeview(fr, columns=[c[0] for c in cols], show="headings",
                          height=height, selectmode="browse")
        for cid, text, w, anchor in cols:
            tv.heading(cid, text=text)
            tv.column(cid, width=sz(w), minwidth=sz(30), anchor=anchor,
                      stretch=(anchor == "w"))
        sb = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return fr, tv

    def _btn_row(self, master, items, cols=4, size=12):
        fr = tk.Frame(master, bg=self.BG)
        for i, (text, cmd) in enumerate(items):
            soft_button(fr, text, cmd, size=size, padx=4).grid(row=i // cols, column=i % cols,
                                            sticky="ew", padx=3, pady=3)
        for c in range(cols):
            fr.columnconfigure(c, weight=1, uniform="b")
        return fr

    def _build_ui(self, s):
        a = self.args
        r = self.root
        r.title("KeyPresser")
        r.configure(bg=self.BG)
        r.attributes("-topmost", True)
        r.minsize(sz(480), sz(420))

        bot = tk.Frame(r, bg=self.BG, padx=10, pady=8)
        bot.pack(side="bottom", fill="x")      # always visible
        topbar = tk.Frame(r, bg=self.BG, padx=8, pady=6)
        topbar.pack(side="top", fill="x")
        tk.Label(topbar, text="KeyPresser", bg=self.BG, fg="#37474f",
                 font=(FONT, sz(14), "bold")).pack(side="left")
        keyboard_button(topbar).pack(side="right")
        soft_button(topbar, f"Aa  {self.ui_size}", self.next_ui_size,
                    size=11, padx=12, pady=7).pack(side="right", padx=(0, 6))
        self.nb = ttk.Notebook(r)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.nb.bind("<<NotebookTabChanged>>",
                     lambda e: self._update_start_text())

        # ---------------- Sequence tab
        sq = tk.Frame(self.nb, bg=self.BG, padx=10, pady=10)
        self.nb.add(sq, text=" ▶ Sequence ")
        top = tk.Frame(sq, bg=self.BG)
        top.pack(fill="x", pady=(0, 4))
        self.seq_btn = big_button(top, "", self.open_seq_list, bg="#37474f",
                                  abg="#455a64", size=14, pady=10)
        self.seq_btn.pack(side="left", fill="x", expand=True)
        big_button(top, "➕ New", self.new_seq, bg="#37474f", abg="#455a64",
                   size=13, pady=10).pack(side="left", padx=(6, 0))
        self._lbl(sq, "Steps run from top to bottom, then start again.",
                  fg="#555").pack(anchor="w")
        fr, self.stree = self._tree(sq, [("n", "#", 36, "center"),
                                         ("name", "Name", 120, "w"),
                                         ("step", "Step", 250, "w"),
                                         ("run", "Runs", 70, "center"),
                                         ("wait", "Then wait", 110,
                                          "center")], height=6)
        fr.pack(fill="both", expand=True, pady=6)
        self.stree.bind("<Double-1>", lambda e: self.edit_step())
        big_button(sq, "➕  Add step", self.add_step, bg=GREEN, abg=GREEN_A,
                   size=14, pady=12).pack(fill="x", pady=(0, 4))
        self._btn_row(sq, [("✏ Edit", self.edit_step),
                           ("🗑 Delete", self.delete_step),
                           ("▲ Up", lambda: self.move_step(-1)),
                           ("▼ Down", lambda: self.move_step(1)),
                           ("⧉ Copy", self.copy_step),
                           ("▶ Test", self.test_step)],
                      cols=6, size=11).pack(fill="x")
        lr = tk.Frame(sq, bg=self.BG)
        lr.pack(anchor="w", pady=(10, 0))
        self._lbl(lr, "Repeat whole sequence:  ", bold=True).pack(side="left")
        self.loops = tk.StringVar(
            value=str(self.seqs[self.cur].get("loops", "0")))
        NumField(lr, self.loops, step=1).pack(side="left")
        self._lbl(lr, "  times (0 = forever)").pack(side="left")

        # ---------------- Key timer tab
        kf = tk.Frame(self.nb, bg=self.BG, padx=14, pady=14)
        self.nb.add(kf, text=" ⌨ Key ")
        self._lbl(kf, "Press a key again and again (own timer).",
                  fg="#555").pack(anchor="w")
        self.key_on = tk.BooleanVar(value=False if a.no_key
                                    else s.get("key_on", True))
        Toggle(kf, "Press key", self.key_on).pack(fill="x", pady=8)
        k = a.key if a.key else s.get("key", "Right Arrow (next)")
        self.key = tk.StringVar(value=k if k in KEYS
                                else "Right Arrow (next)")
        kr = tk.Frame(kf, bg=self.BG)
        kr.pack(fill="x", pady=4)
        self._lbl(kr, "Key:  ", bold=True).pack(side="left")
        self.key_btn = big_button(kr, "", self.choose_key, size=13)
        self.key_btn.pack(side="left", fill="x", expand=True)
        self.key.trace_add("write", lambda *x: self.key_btn.config(
            text=self.key.get() + "   ▾"))
        self.key_btn.config(text=self.key.get() + "   ▾")

        self.kmin = tk.StringVar(value=fmt(a.min if a.min is not None
                                           else fnum(s.get("kmin", 0))))
        self.kmax = tk.StringVar(value=fmt(a.max if a.max is not None
                                           else fnum(s.get("kmax", 2))))
        self._lbl(kf, "Random gap (sec):", bold=True).pack(anchor="w",
                                                          pady=(12, 2))
        g = tk.Frame(kf, bg=self.BG)
        g.pack(anchor="w")
        NumField(g, self.kmin, step=0.5).pack(side="left")
        self._lbl(g, "  to  ").pack(side="left")
        NumField(g, self.kmax, step=0.5).pack(side="left")
        self._lbl(kf, "Stop key after (0 = never):", bold=True
                  ).pack(anchor="w", pady=(12, 2))
        self.limit = tk.StringVar(value=str(a.limit if a.limit is not None
                                            else s.get("limit", "0")))
        NumField(kf, self.limit, step=1).pack(anchor="w")

        # ---------------- Clicks timer tab
        mf = tk.Frame(self.nb, bg=self.BG, padx=10, pady=10)
        self.nb.add(mf, text=" 🖱 Clicks ")
        self.points_on = tk.BooleanVar(value=s.get("points_on", True))
        Toggle(mf, "Click these points (each on its own timer)",
               self.points_on).pack(fill="x")
        fr, self.tree = self._tree(mf, [("n", "#", 40, "center"),
                                        ("xy", "Point (X, Y)", 150, "w"),
                                        ("click", "Click", 80, "center"),
                                        ("every", "Every (sec)", 120,
                                         "center")], height=5)
        fr.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<Double-1>", lambda e: self.edit_point())
        big_button(mf, "📍  Pick point (tap the spot)", self.pick_point,
                   bg=GREEN, abg=GREEN_A, size=14, pady=12
                   ).pack(fill="x", pady=(0, 4))
        self._btn_row(mf, [("✏ Edit", self.edit_point),
                           ("🗑 Delete", self.delete_point),
                           ("▶ Test click", self.test_point)],
                      cols=3).pack(fill="x")
        d = tk.Frame(mf, bg=self.BG)
        d.pack(anchor="w", pady=(8, 0))
        self._lbl(d, "New points every  ", bold=True).pack(side="left")
        self.pmin = tk.StringVar(value=str(s.get("pmin", "10")))
        self.pmax = tk.StringVar(value=str(s.get("pmax", "20")))
        NumField(d, self.pmin, step=1, width=4).pack(side="left")
        self._lbl(d, " to ").pack(side="left")
        NumField(d, self.pmax, step=1, width=4).pack(side="left")
        self._lbl(d, " sec").pack(side="left")
        self.restore = tk.BooleanVar(value=s.get("restore", True))
        Toggle(mf, "Put mouse back after each click", self.restore
               ).pack(fill="x", pady=(8, 0))
        self.mouse_pos = tk.StringVar(value="")
        tk.Label(mf, textvariable=self.mouse_pos, bg=self.BG, fg="#06c",
                 font=(FONT, sz(11))).pack(anchor="w", pady=(4, 0))

        # ---------------- Links timer tab
        lf = tk.Frame(self.nb, bg=self.BG, padx=10, pady=10)
        self.nb.add(lf, text=" 🔗 Links ")
        self.links_on = tk.BooleanVar(value=s.get("links_on", True))
        Toggle(lf, "Open these links in the browser", self.links_on
               ).pack(fill="x")
        fr, self.ltree = self._tree(lf, [("n", "#", 40, "center"),
                                         ("url", "Link", 300, "w"),
                                         ("when", "When", 130, "center")],
                                    height=6)
        fr.pack(fill="both", expand=True, pady=6)
        self.ltree.bind("<Double-1>", lambda e: self.edit_link())
        big_button(lf, "➕  Add link", self.add_link, bg=GREEN, abg=GREEN_A,
                   size=14, pady=12).pack(fill="x", pady=(0, 4))
        self._btn_row(lf, [("✏ Edit", self.edit_link),
                           ("🗑 Delete", self.delete_link),
                           ("▶ Test open", self.test_link)],
                      cols=3).pack(fill="x")
        self._lbl(lf, "Once = opens one time at Start.  Repeat = opens at "
                  "Start, then on its timer.\nEach open makes a new tab.",
                  size=10, fg="#666").pack(anchor="w", pady=(6, 0))

        # ---------------- bottom bar (shared)
        row = tk.Frame(bot, bg=self.BG)
        row.pack(fill="x")
        self._lbl(row, "Start delay (sec) ", bold=True).pack(side="left")
        self.delay = tk.StringVar(value=str(a.delay if a.delay is not None
                                            else s.get("delay", "3")))
        NumField(row, self.delay, step=1, width=3).pack(side="left")
        self.hide = tk.BooleanVar(value=s.get("hide", True))
        Toggle(row, "Small Stop button while running", self.hide
               ).pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.start_btn = big_button(bot, "", self.toggle, bg=GREEN,
                                    abg=GREEN_A, size=17, pady=14)
        self.start_btn.pack(fill="x", pady=(8, 4))
        self.status = tk.StringVar(value="Ready")
        tk.Label(bot, textvariable=self.status, bg=self.BG, fg=GREEN,
                 font=(FONT, sz(12))).pack()
        self.count_var = tk.StringVar(value="")
        tk.Label(bot, textvariable=self.count_var, bg=self.BG,
                 font=(FONT, sz(12), "bold")).pack()
        self._update_start_text()
        self._update_seq_btn()
        self._fit_window()

    def _fit_window(self):
        r = self.root
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        # small screen / high scaling: show fewer list rows so every button
        # stays visible
        over = r.winfo_reqheight() - (sh - 90)
        if over > 0:
            rowh = 46
            try:
                rowh = int(ttk.Style().lookup("Treeview", "rowheight")) or 46
            except Exception:
                pass
            for tv in (self.stree, self.tree, self.ltree):
                cur = int(tv.cget("height"))
                tv.configure(height=max(1, cur - (over + rowh - 1) // rowh))
            r.update_idletasks()
        w = min(max(r.winfo_reqwidth(), 560), sw - 20)
        h = min(r.winfo_reqheight(), sh - 90)
        r.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+10")

    def mode(self):
        if self.args.mode:
            return self.args.mode
        return "sequence" if self.nb.index("current") == 0 else "timers"

    def _update_start_text(self):
        if not hasattr(self, "start_btn") or self.running():
            return
        nm = self.seqs[self.cur]["name"] if self.seqs else ""
        txt = (f"▶  START:  {nm}" if self.mode() == "sequence"
               else "▶  START TIMERS  (Key + Clicks + Links)")
        self.start_btn.config(text=txt, bg=GREEN, activebackground=GREEN_A)

    def _refresh_all(self):
        self._refresh_steps()
        self._refresh_points()
        self._refresh_links()

    def _refresh_steps(self, select=None):
        self._update_seq_btn()
        self._update_start_text()
        self.stree.delete(*self.stree.get_children())
        for i, st in enumerate(self.steps):
            self.stree.insert("", "end", iid=str(i), values=(
                i + 1, st.get("name", ""), describe(st),
                "Once" if st.get("run") == "once" else "Every",
                span(st.get("amin", 0), st.get("amax", 0)) + " s"))
        if select is not None and 0 <= select < len(self.steps):
            self.stree.selection_set(str(select))
            self.stree.see(str(select))

    def _refresh_points(self):
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(self.points):
            self.tree.insert("", "end", iid=str(i), values=(
                i + 1, f"{p['x']}, {p['y']}", p.get("click", "Left"),
                span(p["min"], p["max"])))

    def _refresh_links(self):
        self.ltree.delete(*self.ltree.get_children())
        for i, l in enumerate(self.links):
            when = ("Once" if l["mode"] == "once"
                    else f"Every {span(l['min'], l['max'])}s")
            self.ltree.insert("", "end", iid=str(i),
                              values=(i + 1, l["url"], when))

    def _track_mouse(self):
        try:
            x, y = self.msc.position
            self.mouse_pos.set(f"Mouse/finger now at X {int(x)}, Y {int(y)}")
        except Exception:
            pass
        self.root.after(150, self._track_mouse)

    @staticmethod
    def _sel(tv):
        s = tv.selection()
        return int(s[0]) if s else None

    # ---------------------------------------------------------- steps
    def next_ui_size(self):
        """Small -> Medium -> Large: rebuild the window at the new size."""
        if self.running():
            return
        names = list(SIZES)
        nxt = names[(names.index(self.ui_size) + 1) % len(names)
                    if self.ui_size in names else 1]
        s = self._state()
        tab = self.nb.index("current")
        global SCALE
        self.ui_size = nxt
        s["ui_size"] = nxt
        SCALE = SIZES[nxt]
        for w in self.root.winfo_children():
            w.destroy()
        self._style()
        self._build_ui(s)
        self._refresh_all()
        self.nb.select(tab)
        self._save_settings()
        self.status.set(f"Size: {nxt}")

    def _sync_loops(self):
        if hasattr(self, "loops") and 0 <= self.cur < len(self.seqs):
            self.seqs[self.cur]["loops"] = self.loops.get()
        return self.seqs

    def _update_seq_btn(self):
        if hasattr(self, "seq_btn"):
            sq = self.seqs[self.cur]
            self.seq_btn.config(text=f"📂  {sq['name']}   "
                                f"({len(sq['steps'])} steps)   ▾")

    def switch_seq(self, i, save=True):
        if 0 <= self.cur < len(self.seqs):
            self._sync_loops()
        self.cur = i
        self.steps = self.seqs[i]["steps"]
        if hasattr(self, "loops"):
            self.loops.set(str(self.seqs[i].get("loops", "0")))
        if hasattr(self, "stree"):
            self._refresh_steps()
        self._update_seq_btn()
        self._update_start_text()
        if save:
            self._save_settings()

    def open_seq_list(self):
        if self.running():
            return
        i = SeqListDialog(self).run()
        if i is not None and 0 <= i < len(self.seqs):
            if i != self.cur:
                self.switch_seq(i)
        self._update_seq_btn()
        if self.args.quit_after_pick:
            self.close()

    def new_seq(self):
        if self.running():
            return
        names = {s["name"].lower() for s in self.seqs}
        n = len(self.seqs) + 1
        while f"sequence {n}" in names:
            n += 1
        name = NameDialog(self.root, "New sequence", f"Sequence {n}").run()
        if name:
            self.seqs.append({"name": name, "loops": "0", "steps": []})
            self.switch_seq(len(self.seqs) - 1)
            self.status.set(f"New sequence '{name}' - now add steps")

    def add_step(self):
        if self.running():
            return
        base = {"type": "click", "x": 0, "y": 0, "button": "Left",
                "times": 1, "tmin": 0.5, "tmax": 1, "amin": 0, "amax": 2}
        st = StepDialog(self.root, base).run()
        if st:
            i = self._sel(self.stree)
            pos = len(self.steps) if i is None else i + 1
            self.steps.insert(pos, st)
            self._refresh_steps(select=pos)
            self._save_settings()

    def edit_step(self, i=None):
        if i is None:
            i = self._sel(self.stree)
        if i is None or self.running() or not (0 <= i < len(self.steps)):
            return
        st = StepDialog(self.root, self.steps[i]).run()
        if st:
            self.steps[i] = st
            self._refresh_steps(select=i)
            self._save_settings()
        if self.args.quit_after_pick:
            self.close()

    def delete_step(self):
        i = self._sel(self.stree)
        if i is None or self.running():
            return
        if messagebox.askyesno("Delete", f"Delete step {i + 1}?",
                               parent=self.root):
            del self.steps[i]
            self._refresh_steps(select=min(i, len(self.steps) - 1))
            self._save_settings()

    def move_step(self, d):
        i = self._sel(self.stree)
        if i is None or self.running():
            return
        j = i + d
        if 0 <= j < len(self.steps):
            self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
            self._refresh_steps(select=j)
            self._save_settings()

    def copy_step(self):
        i = self._sel(self.stree)
        if i is None or self.running():
            return
        self.steps.insert(i + 1, dict(self.steps[i]))
        self._refresh_steps(select=i + 1)
        self._save_settings()

    def test_step(self):
        i = self._sel(self.stree)
        if i is None or self.running():
            return
        st = dict(self.steps[i])
        st["amin"] = st["amax"] = 0
        self._launch(lambda: self.work_sequence(
            {"steps": [st], "loops": 1, "delay": 1}, test=True))

    # ---------------------------------------------------------- points
    def pick_point(self):
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
        a, b = sorted((fnum(self.pmin.get(), 10), fnum(self.pmax.get(), 20)))
        self.points.append({"x": int(x), "y": int(y), "min": a, "max": b,
                            "click": "Left"})
        self._refresh_points()
        self._save_settings()
        self.status.set(f"Added point {len(self.points)} at {int(x)}, {int(y)}")

    def edit_point(self):
        i = self._sel(self.tree)
        if i is None or self.running():
            return
        p = PointDialog(self.root, self.points[i]).run()
        if p:
            self.points[i] = p
            self._refresh_points()
            self._save_settings()

    def delete_point(self):
        i = self._sel(self.tree)
        if i is None or self.running():
            return
        del self.points[i]
        self._refresh_points()
        self._save_settings()

    def test_point(self):
        i = self._sel(self.tree)
        if i is None or self.running():
            return
        p = self.points[i]
        self.do_click(p["x"], p["y"], p.get("click", "Left"),
                      self.restore.get())

    # ---------------------------------------------------------- links
    def add_link(self):
        if self.running():
            return
        l = LinkDialog(self.root, {"url": "", "mode": "once", "min": 30,
                                   "max": 60}).run()
        if l:
            self.links.append(l)
            self._refresh_links()
            self._save_settings()

    def edit_link(self):
        i = self._sel(self.ltree)
        if i is None or self.running():
            return
        l = LinkDialog(self.root, self.links[i]).run()
        if l:
            self.links[i] = l
            self._refresh_links()
            self._save_settings()

    def delete_link(self):
        i = self._sel(self.ltree)
        if i is None or self.running():
            return
        del self.links[i]
        self._refresh_links()
        self._save_settings()

    def test_link(self):
        i = self._sel(self.ltree)
        if i is not None:
            open_link(self.links[i]["url"])

    def choose_key(self):
        k = KeyChooser(self.root, self.key.get()).run()
        if k:
            self.key.set(k)
            self._save_settings()

    # ---------------------------------------------------------- actions
    def do_click(self, x, y, kind, restore):
        """Click at x, y. If the small Stop window is in the way, hide it
        for a moment."""
        r = self.mini_rect
        covered = r and r[0] <= x <= r[2] and r[1] <= y <= r[3]
        if covered:
            self.q.put(("mini_hide", None))
            time.sleep(0.25)
        old = self.msc.position
        self.msc.position = (x, y)
        time.sleep(0.05)
        if kind == "Right":
            self.msc.click(Button.right, 1)
        elif kind == "Double":
            self.msc.click(Button.left, 2)
        else:
            self.msc.click(Button.left, 1)
        if restore:
            time.sleep(0.05)
            self.msc.position = old
        if covered:
            time.sleep(0.1)
            self.q.put(("mini_show", None))

    def press_key(self, name):
        keys = KEYS.get(name, (Key.right,))
        self.sending = True
        try:
            for k in keys:
                self.kbc.press(k)
                time.sleep(0.02)
            time.sleep(0.03)
            for k in reversed(keys):
                self.kbc.release(k)
                time.sleep(0.01)
        finally:
            time.sleep(0.02)
            self.sending = False

    def log(self, text):
        self.q.put(("log", text))

    # ---------------------------------------------------------- hotkeys
    def _on_key(self, key):
        if key == Key.f8:
            self.q.put(("toggle", None))
        elif key == Key.f7:
            self.q.put(("addpoint", None))
        elif key == Key.esc and not self.sending:
            self.q.put(("stop", None))

    # ---------------------------------------------------------- run
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
        delay = max(0, int(fnum(self.delay.get(), 3)))
        if self.mode() == "sequence":
            if not self.steps:
                self.status.set("Add at least one step first")
                return
            cfg = {"steps": [dict(s) for s in self.steps],
                   "loops": max(0, int(fnum(self.loops.get()))),
                   "delay": delay}
            target = lambda: self.work_sequence(cfg)
        else:
            kmin, kmax = sorted((max(0, fnum(self.kmin.get())),
                                 max(0, fnum(self.kmax.get(), 2))))
            cfg = {"key_on": self.key_on.get(), "key": self.key.get(),
                   "kmin": kmin, "kmax": kmax,
                   "limit": max(0, int(fnum(self.limit.get()))),
                   "delay": delay,
                   "points": ([dict(p) for p in self.points]
                              if self.points_on.get() else []),
                   "links": ([dict(l) for l in self.links]
                             if self.links_on.get() else []),
                   "restore": self.restore.get(),
                   "run_for": self.args.run_for}
            if not cfg["key_on"] and not cfg["points"] and not cfg["links"]:
                self.status.set("Turn on the key, or add a click point "
                                "or link")
                return
            target = lambda: self.work_timers(cfg)
        self._save_settings()
        self._launch(target)

    def _launch(self, target):
        self.stop.clear()
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()
        self.start_btn.config(text="■  STOP", bg=RED, activebackground=RED_A)
        if self.hide.get():
            self.show_mini()

    # floating mini Stop window --------------------------------------
    def show_mini(self):
        self.root.withdraw()
        m = self.mini = tk.Toplevel(self.root)
        m.overrideredirect(True)
        m.attributes("-topmost", True)
        m.configure(bg="#263238")
        handle = tk.Label(m, text="⠿ drag", bg="#263238", fg="#90a4ae",
                          font=(FONT, sz(10)))
        handle.pack(fill="x")
        self.mini_status = tk.Label(m, text="Starting...", bg="#263238",
                                    fg="white", font=(FONT, sz(10)),
                                    wraplength=sz(210), justify="center")
        self.mini_status.pack(padx=8)
        big_button(m, "■  STOP", self.stop.set, bg=RED, abg=RED_A,
                   size=16, padx=34, pady=12).pack(padx=8, pady=8)
        m.update_idletasks()
        w = max(sz(230), m.winfo_reqwidth())
        x = self.root.winfo_screenwidth() - w - 20
        m.geometry(f"{w}x{m.winfo_reqheight()}+{x}+20")

        def press(e):
            m._dx, m._dy = e.x_root - m.winfo_x(), e.y_root - m.winfo_y()

        def drag(e):
            m.geometry(f"+{e.x_root - m._dx}+{e.y_root - m._dy}")
            self._update_mini_rect()

        for wdg in (handle, self.mini_status, m):
            wdg.bind("<ButtonPress-1>", press)
            wdg.bind("<B1-Motion>", drag)
        m.after(100, self._update_mini_rect)

    def _update_mini_rect(self):
        m = self.mini
        if m:
            m.update_idletasks()
            x, y = m.winfo_rootx(), m.winfo_rooty()
            self.mini_rect = (x - 2, y - 2, x + m.winfo_width() + 2,
                              y + m.winfo_height() + 2)

    def close_mini(self):
        if self.mini:
            try:
                self.mini.destroy()
            except Exception:
                pass
            self.mini = None
            self.mini_rect = None
            self.root.deiconify()

    # timing helpers ---------------------------------------------------
    def wait_until(self, t):
        while not self.stop.is_set():
            left = t - time.perf_counter()
            if left <= 0:
                return True
            time.sleep(min(left, 0.01))
        return False

    def wait(self, secs):
        return self.wait_until(time.perf_counter() + max(0.0, secs))

    def countdown(self, n):
        for s in range(n, 0, -1):
            self.q.put(("status", f"Starting in {s}..."))
            if not self.wait(1):
                return False
        return True

    # sequence worker ----------------------------------------------------
    def work_sequence(self, cfg, test=False):
        steps, loops = cfg["steps"], cfg["loops"]
        n = {"click": 0, "key": 0, "link": 0}
        if not self.countdown(cfg["delay"]):
            self.q.put(("finished", "Stopped"))
            return
        loop = 0
        every = any(st.get("run") != "once" for st in steps)
        while (loops == 0 or loop < loops) and not self.stop.is_set():
            if loop >= 1 and not every:
                break          # only "once" steps: nothing left to repeat
            loop += 1
            total = "∞" if loops == 0 else loops
            for i, st in enumerate(steps):
                if self.stop.is_set():
                    break
                if not test:
                    self.q.put(("highlight", i))
                if st.get("run") == "once" and loop > 1:
                    continue
                nm = st.get("name") or ""
                label = (f"Loop {loop}/{total} · step {i + 1}/{len(steps)}"
                         + (f" · {nm}" if nm else ""))
                self.q.put(("status", label))
                t = st.get("type")
                times = max(1, int(st.get("times", 1)))
                if t in ("click", "key"):
                    for k in range(times):
                        if self.stop.is_set():
                            break
                        if t == "click":
                            self.do_click(st["x"], st["y"],
                                          st.get("button", "Left"), True)
                            n["click"] += 1
                            self.log(f"seq {loop} {i + 1} click "
                                     f"{st['x']} {st['y']}")
                        else:
                            self.press_key(st.get("key"))
                            n["key"] += 1
                            self.log(f"seq {loop} {i + 1} key "
                                     f"{st.get('key')}")
                        self.q.put(("count", n))
                        if k < times - 1:
                            self.wait(random.uniform(st.get("tmin", 0),
                                                     st.get("tmax", 0)))
                elif t == "link":
                    open_link(st["url"])
                    n["link"] += 1
                    self.log(f"seq {loop} {i + 1} link {st['url']}")
                    self.q.put(("count", n))
                gap = random.uniform(st.get("amin", 0), st.get("amax", 0))
                if gap > 0 and not self.stop.is_set():
                    self.q.put(("status", f"{label} · waiting {gap:.1f}s"))
                    self.wait(gap)
        done = (f"{n['click']} clicks, {n['key']} key presses, "
                f"{n['link']} links")
        self.q.put(("finished", ("Stopped · " if self.stop.is_set()
                                 else "Done · ") + done))

    # timers worker -------------------------------------------------------
    def work_timers(self, cfg):
        if not self.countdown(cfg["delay"]):
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
        n = {"click": 0, "key": 0, "link": 0}
        self.q.put(("status", "Running timers..."))
        while tasks and not self.stop.is_set():
            t = min(tasks, key=lambda x: x["next"])
            if deadline and t["next"] > deadline:
                self.wait_until(deadline)
                break
            if not self.wait_until(t["next"]):
                break
            if t["kind"] == "key":
                self.press_key(cfg["key"])
                n["key"] += 1
                self.log(f"key {n['key']}")
                if cfg["limit"] and n["key"] >= cfg["limit"]:
                    tasks.remove(t)
                else:
                    t["next"] = time.perf_counter() + random.uniform(
                        cfg["kmin"], cfg["kmax"])
            elif t["kind"] == "link":
                l = t["l"]
                open_link(l["url"])
                n["link"] += 1
                self.log(f"link {t['i'] + 1} {l['url']}")
                if l["mode"] == "once":
                    tasks.remove(t)
                else:
                    t["next"] = time.perf_counter() + random.uniform(
                        l["min"], l["max"])
            else:
                p = t["p"]
                self.do_click(p["x"], p["y"], p.get("click", "Left"),
                              cfg["restore"])
                n["click"] += 1
                self.log(f"click {t['i'] + 1} {p['x']} {p['y']}")
                t["next"] = time.perf_counter() + random.uniform(p["min"],
                                                                 p["max"])
            self.q.put(("count", n))
        done = (f"{n['key']} key presses, {n['click']} clicks, "
                f"{n['link']} links")
        self.q.put(("finished", ("Stopped · " if self.stop.is_set()
                                 else "Done · ") + done))

    # ---------------------------------------------------------- main loop
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
                    if self.mini:
                        self.mini_status.config(text=val)
                elif msg == "highlight":
                    if str(val) in self.stree.get_children():
                        self.stree.selection_set(str(val))
                        self.stree.see(str(val))
                elif msg == "count":
                    self.count_var.set(f"Clicks: {val['click']} · Keys: "
                                       f"{val['key']} · Links: {val['link']}")
                elif msg == "mini_hide" and self.mini:
                    self.mini.withdraw()
                elif msg == "mini_show" and self.mini:
                    self.mini.deiconify()
                elif msg == "log":
                    if self.logfile:
                        self.logfile.write(f"{time.time():.3f} {val}\n")
                        self.logfile.flush()
                elif msg == "finished":
                    self.close_mini()
                    self.status.set(val)
                    self._update_start_text()
                    self.start_btn.config(bg=GREEN, activebackground=GREEN_A)
                    if self.args.quit_when_done:
                        self.close()
                        return
        except queue.Empty:
            pass
        if not self.running() and self.start_btn["bg"] == RED:
            self._update_start_text()
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
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["sequence", "timers"], default=None)
    p.add_argument("--seq-file", default="")
    p.add_argument("--seq", default="", help="sequence name to select")
    p.add_argument("--open-seq-list", action="store_true")
    p.add_argument("--show-keyboard", action="store_true")
    p.add_argument("--ui-size", choices=list(SIZES), default=None)
    p.add_argument("--key", default=None)
    p.add_argument("--no-key", action="store_true")
    p.add_argument("--min", type=float, default=None)
    p.add_argument("--max", type=float, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--delay", type=int, default=None)
    p.add_argument("--point", action="append", help="X,Y,MIN,MAX")
    p.add_argument("--link", action="append", help="URL or URL|MIN|MAX")
    p.add_argument("--open-picker", action="store_true")
    p.add_argument("--open-step-editor", type=int, default=None)
    p.add_argument("--quit-after-pick", action="store_true")
    p.add_argument("--tab", default="")
    p.add_argument("--run-for", type=float, default=0)
    p.add_argument("--start", action="store_true")
    p.add_argument("--quit-when-done", action="store_true")
    p.add_argument("--no-settings", action="store_true")
    p.add_argument("--log", default="")
    args, _ = p.parse_known_args()
    root = tk.Tk()
    global FONT
    try:
        fams = set(tkfont.families(root))
        for f in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"):
            if f in fams:
                FONT = f
                break
    except Exception:
        pass
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
