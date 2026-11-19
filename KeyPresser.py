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

import sys as _sys
_sys.coinit_flags = 0          # comtypes: use a multithreaded COM apartment

import argparse
import ctypes
import re
import json
import shutil
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
from tkinter import ttk, messagebox, filedialog

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
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
# what belongs to a project (everything else is an app-wide setting)
PROJECT_KEYS = ("seqs", "cur", "steps", "loops", "key_on", "key", "kmin",
                "kmax", "limit", "pmin", "pmax", "restore", "points",
                "points_on", "links_on", "links")


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip()) or "Project"


def project_path(name):
    return os.path.join(PROJECTS_DIR, safe_name(name) + ".json")


def list_projects():
    try:
        return sorted((f[:-5] for f in os.listdir(PROJECTS_DIR)
                       if f.lower().endswith(".json")), key=str.lower)
    except OSError:
        return []


def read_project(name):
    try:
        with open(project_path(name), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def write_project(name, data):
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    d = {k: v for k, v in data.items() if k in PROJECT_KEYS}
    d["keypresser_project"] = 1
    path = project_path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def new_project_data():
    return {"seqs": [{"name": "Sequence 1", "loops": "0", "steps": []}],
            "cur": 0}

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


def draw_box_on_screen(root, on_done, hide=()):
    """Dim the screen; drag a box with finger or mouse.
    on_done((left, top, right, bottom)) or on_done(None) if cancelled."""
    for w in hide:
        w.withdraw()
    x0, y0, w, h = screen_area(root)
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.geometry(f"{w}x{h}+{x0}+{y0}")
    ov.attributes("-topmost", True)
    try:
        ov.attributes("-alpha", 0.35)
    except Exception:
        pass
    c = tk.Canvas(ov, bg="black", highlightthickness=0, cursor="crosshair")
    c.pack(fill="both", expand=True)
    state = {"start": None, "rect": None, "lbl": None}

    ban = tk.Toplevel(root)
    ban.overrideredirect(True)
    ban.attributes("-topmost", True)
    ban.configure(bg="#1e3a5f")
    tk.Label(ban, text="Drag a box around where the word is", bg="#1e3a5f",
             fg="white", font=(FONT, 18, "bold")).pack(padx=24, pady=(14, 4))
    tk.Label(ban, text="press, drag, then let go", bg="#1e3a5f",
             fg="#cfe0f5", font=(FONT, 11)).pack()
    tk.Button(ban, text="CANCEL", bg=RED, fg="white", bd=0,
              activebackground=RED_A, activeforeground="white",
              font=(FONT, 14, "bold"), padx=30, pady=6,
              command=lambda: finish(None)).pack(pady=(10, 14))
    ban.update_idletasks()
    ban.geometry(f"+{(root.winfo_screenwidth() - ban.winfo_reqwidth()) // 2}"
                 f"+40")

    def finish(box):
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
        on_done(box)

    def press(e):
        state["start"] = (e.x_root, e.y_root)
        if state["rect"]:
            c.delete(state["rect"])
            c.delete(state["lbl"])
        state["rect"] = c.create_rectangle(
            e.x_root - x0, e.y_root - y0, e.x_root - x0, e.y_root - y0,
            outline="#ffeb3b", width=3, fill="white", stipple="gray25")
        state["lbl"] = c.create_text(e.x_root - x0, e.y_root - y0 - 14,
                                     anchor="w", fill="#ffeb3b",
                                     font=(FONT, 12, "bold"), text="")

    def move(e):
        if not state["start"]:
            return
        sx, sy = state["start"]
        c.coords(state["rect"], sx - x0, sy - y0, e.x_root - x0,
                 e.y_root - y0)
        c.coords(state["lbl"], min(sx, e.x_root) - x0,
                 min(sy, e.y_root) - y0 - 14)
        c.itemconfig(state["lbl"], text=f"{abs(e.x_root - sx)} × "
                                        f"{abs(e.y_root - sy)}")

    def release(e):
        if not state["start"]:
            return
        sx, sy = state["start"]
        l, r = sorted((sx, e.x_root))
        t, b = sorted((sy, e.y_root))
        if r - l < 8 or b - t < 8:          # just a tap: try again
            state["start"] = None
            return
        finish((l, t, r, b))

    c.bind("<ButtonPress-1>", press)
    c.bind("<B1-Motion>", move)
    c.bind("<ButtonRelease-1>", release)
    ov.bind("<Escape>", lambda e: finish(None))

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


def show_box_overlay(root, box, secs=2.5, color="#ffeb3b"):
    """Outline a box on screen for a moment (click-through)."""
    x0, y0, w, h = screen_area(root)
    key = "#ff00fe"
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.attributes("-topmost", True)
    try:
        ov.attributes("-transparentcolor", key)
    except Exception:
        pass
    ov.geometry(f"{w}x{h}+{x0}+{y0}")
    c = tk.Canvas(ov, bg=key, highlightthickness=0)
    c.pack(fill="both", expand=True)
    l, t, r, b = box
    c.create_rectangle(l - x0, t - y0, r - x0, b - y0, outline=color,
                       width=4)
    c.create_text(l - x0 + 4, t - y0 - 14, anchor="w", fill=color,
                  font=(FONT, 12, "bold"), text=f"{int(r - l)} × {int(b - t)}")
    ov.after(int(secs * 1000), ov.destroy)


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
# reading text on screen (Windows text first, then Windows OCR)
# ====================================================================
def _grab_bgra(x, y, w, h, scale=1):
    """Screen pixels of a box as BGRA bytes (no extra libraries)."""
    from ctypes import wintypes as wt
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    u.GetDC.restype = wt.HDC
    u.GetDC.argtypes = [wt.HWND]
    u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    g.CreateCompatibleDC.restype = wt.HDC
    g.CreateCompatibleDC.argtypes = [wt.HDC]
    g.CreateCompatibleBitmap.restype = wt.HBITMAP
    g.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    g.SelectObject.restype = wt.HGDIOBJ
    g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    g.StretchBlt.argtypes = [wt.HDC] + [ctypes.c_int] * 4 + [wt.HDC] + \
        [ctypes.c_int] * 4 + [wt.DWORD]
    g.SetStretchBltMode.argtypes = [wt.HDC, ctypes.c_int]
    g.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    g.DeleteObject.argtypes = [wt.HGDIOBJ]
    g.DeleteDC.argtypes = [wt.HDC]

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32),
                    ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    W, H = int(w * scale), int(h * scale)
    sdc = u.GetDC(None)
    mdc = g.CreateCompatibleDC(sdc)
    bmp = g.CreateCompatibleBitmap(sdc, W, H)
    old = g.SelectObject(mdc, bmp)
    g.SetStretchBltMode(mdc, 4)                      # HALFTONE = smooth
    g.StretchBlt(mdc, 0, 0, W, H, sdc, int(x), int(y), int(w), int(h),
                 0x00CC0020)                          # SRCCOPY
    bi = BMIH()
    bi.biSize, bi.biWidth, bi.biHeight = ctypes.sizeof(BMIH), W, -H
    bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(W * H * 4)
    g.GetDIBits(mdc, bmp, 0, H, buf, ctypes.byref(bi), 0)
    g.SelectObject(mdc, old)
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(None, sdc)
    return buf.raw, W, H


def _ocr_text(x, y, w, h):
    """Windows built-in OCR (Windows 10/11)."""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import (SoftwareBitmap,
                                                BitmapPixelFormat,
                                                BitmapAlphaMode)
    from winrt.windows.storage.streams import DataWriter
    eng = OcrEngine.try_create_from_user_profile_languages()
    if eng is None:
        raise RuntimeError("Windows OCR is not available (add a language "
                           "in Windows settings)")
    big = max(w, h)
    scale = 2 if big * 2 <= 2500 else 1     # bigger text reads better
    data, W, H = _grab_bgra(x, y, w, h, scale)
    dw = DataWriter()
    dw.write_bytes(data)
    sb = SoftwareBitmap.create_copy_from_buffer(
        dw.detach_buffer(), BitmapPixelFormat.BGRA8, W, H,
        BitmapAlphaMode.IGNORE)

    async def run():
        return await eng.recognize_async(sb)

    return (asyncio.run(run()).text or "").strip()


def _uia_text(x, y):
    """Text Windows reports for the button / label / box at the point."""
    import comtypes
    import comtypes.client
    try:
        from comtypes.gen import UIAutomationClient as UIA
    except ImportError:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    uia = comtypes.client.CreateObject(UIA.CUIAutomation,
                                       interface=UIA.IUIAutomation)
    el = uia.ElementFromPoint(UIA.tagPOINT(int(x), int(y)))
    parts = []
    try:
        if el.CurrentName:
            parts.append(el.CurrentName.strip())
    except Exception:
        pass
    try:
        vp = el.GetCurrentPattern(10002)                 # ValuePattern
        if vp:
            v = vp.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue
            if v and v.strip() and v.strip() not in parts:
                parts.append(v.strip())
    except Exception:
        pass
    return " ".join(p for p in parts if p)


def read_screen_text(method, x, y, w, h, want=None):
    """Read text at / around (x, y).
    method: 'auto' (Windows text, then OCR), 'uia' or 'ocr'.
    want: optional function(text)->bool; in auto mode OCR is also tried
    when the Windows text doesn't match.
    Returns (text, source, error)."""
    out = {"text": "", "src": "", "err": ""}

    def work():
        try:
            import comtypes
            comtypes.CoInitializeEx(0)
        except Exception:
            pass
        order = {"uia": ["uia"], "ocr": ["ocr"]}.get(method, ["uia", "ocr"])
        errs = []
        for m in order:
            try:
                if m == "uia":
                    t = _uia_text(x, y)
                else:
                    t = _ocr_text(int(x - w / 2), int(y - h / 2), int(w),
                                  int(h))
            except Exception as e:
                errs.append(f"{m}: {e}")
                continue
            if t:
                out["text"], out["src"] = t, m
                if want is None or want(t):
                    break
        if not out["text"] and errs:
            out["err"] = "; ".join(errs)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(15)
    return out["text"], out["src"], out["err"]


NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


# ---------------------------------------------------------------------
# finding a word / button on screen (for the Find & click step)
# ---------------------------------------------------------------------
def virtual_screen():
    try:
        gm = ctypes.windll.user32.GetSystemMetrics
        w, h = gm(78), gm(79)
        if w > 0 and h > 0:
            return gm(76), gm(77), w, h
    except Exception:
        pass
    return 0, 0, 1920, 1080


def run_com(fn, timeout=25):
    """Run fn() in its own COM-ready thread; returns its result."""
    out = {}

    def work():
        try:
            import comtypes
            comtypes.CoInitializeEx(0)
        except Exception:
            pass
        try:
            out["r"] = fn()
        except Exception as e:
            out["e"] = e

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout)
    if "e" in out:
        raise out["e"]
    if "r" not in out:
        raise TimeoutError("took too long")
    return out["r"]


def _norm(t):
    return " ".join((t or "").split()).lower()


def find_spans(mode, kw, text):
    """Where kw occurs in text, as (start, end) pairs."""
    text = text or ""
    if mode == "regex":
        try:
            return [(m.start(), m.end()) for m in re.finditer(kw, text, re.I)
                    if m.end() > m.start()]
        except re.error:
            return []
    if mode == "equals":
        return [(0, len(text))] if _norm(text) == _norm(kw) and kw else []
    if not kw:
        return []
    return [(m.start(), m.end())
            for m in re.finditer(re.escape(kw), text, re.I)]


def _ocr_words(x0, y0, w, h):
    """OCR an area. Returns [(line_text, [(word, (l, t, r, b)), ...])] in
    screen coordinates."""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import (SoftwareBitmap,
                                                BitmapPixelFormat,
                                                BitmapAlphaMode)
    from winrt.windows.storage.streams import DataWriter
    eng = OcrEngine.try_create_from_user_profile_languages()
    if eng is None:
        raise RuntimeError("Windows OCR is not available")
    big = max(w, h)
    scale = 2.0 if big * 2 <= 2500 else min(1.0, 2500.0 / big)
    data, W, H = _grab_bgra(x0, y0, w, h, scale)
    dw = DataWriter()
    dw.write_bytes(data)
    sb = SoftwareBitmap.create_copy_from_buffer(
        dw.detach_buffer(), BitmapPixelFormat.BGRA8, W, H,
        BitmapAlphaMode.IGNORE)

    async def run():
        return await eng.recognize_async(sb)

    res = asyncio.run(run())
    sx, sy = W / float(w), H / float(h)
    lines = []
    for ln in res.lines:
        words = []
        for wd in ln.words:
            r = wd.bounding_rect
            l, t = x0 + r.x / sx, y0 + r.y / sy
            words.append((wd.text, (l, t, l + r.width / sx,
                                    t + r.height / sy)))
        lines.append((" ".join(wt for wt, _ in words), words))
    return lines


def _ocr_matches(lines, mode, kw):
    out, seen = [], set()

    def add(text, rects):
        l = min(r[0] for r in rects)
        t = min(r[1] for r in rects)
        r_ = max(r[2] for r in rects)
        b = max(r[3] for r in rects)
        key = (round(l), round(t), round(r_), round(b))
        if key not in seen:
            seen.add(key)
            out.append({"text": text, "rect": (l, t, r_, b), "src": "ocr"})

    for text, words in lines:
        offs, pos = [], 0
        for wt, rect in words:
            offs.append((pos, pos + len(wt), rect, wt))
            pos += len(wt) + 1
        if mode == "equals":
            for a, b, rect, wt in offs:
                if _norm(wt) == _norm(kw):
                    add(wt, [rect])
        for s0, e0 in find_spans(mode, kw, text):
            rs = [rect for a, b, rect, wt in offs if a < e0 and b > s0]
            if rs:
                add(text[s0:e0], rs)
    return out


def _uia_find(x0, y0, w, h, whole, want):
    """Buttons / texts whose name matches, using Windows UI Automation."""
    import comtypes.client
    try:
        from comtypes.gen import UIAutomationClient as UIA
    except ImportError:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    uia = comtypes.client.CreateObject(UIA.CUIAutomation,
                                       interface=UIA.IUIAutomation)
    if whole:
        top = uia.ElementFromHandle(ctypes.windll.user32.GetForegroundWindow())
    else:
        top = uia.ElementFromPoint(UIA.tagPOINT(int(x0 + w / 2),
                                                int(y0 + h / 2)))
        root = uia.GetRootElement()
        walker = uia.ControlViewWalker
        for _ in range(80):
            par = walker.GetParentElement(top)
            if not par or uia.CompareElements(par, root):
                break
            top = par
    cr = uia.CreateCacheRequest()
    cr.AddProperty(30005)                         # Name
    cr.AddProperty(30001)                         # BoundingRectangle
    cond = uia.CreatePropertyCondition(30022, False)   # not off-screen
    arr = top.FindAllBuildCache(4, cond, cr)      # 4 = all descendants
    out = []
    for i in range(arr.Length if arr else 0):
        e = arr.GetElement(i)
        try:
            name = e.CachedName
            if not name or not want(name):
                continue
            r = e.CachedBoundingRectangle
            l, t, r_, b = r.left, r.top, r.right, r.bottom
        except Exception:
            continue
        if r_ - l <= 0 or b - t <= 0:
            continue
        cx, cy = (l + r_) / 2, (t + b) / 2
        if x0 <= cx <= x0 + w and y0 <= cy <= y0 + h:
            out.append({"text": name.strip(), "rect": (l, t, r_, b),
                        "src": "uia"})
    return out


def find_area(st):
    if st.get("whole", True):
        return virtual_screen()
    aw, ah = fnum(st.get("aw", 300)), fnum(st.get("ah", 60))
    return (int(st.get("x", 0) - aw / 2), int(st.get("y", 0) - ah / 2),
            int(aw), int(ah))


def _find_raw(method, mode, kw, area, whole):
    x0, y0, w, h = area
    order = {"uia": ["uia"], "ocr": ["ocr"]}.get(method, ["uia", "ocr"])
    errs = []
    for m in order:
        try:
            if m == "uia":
                found = _uia_find(x0, y0, w, h, whole,
                                  lambda nm: bool(find_spans(mode, kw, nm)))
            else:
                found = _ocr_matches(_ocr_words(x0, y0, w, h), mode, kw)
        except Exception as e:
            errs.append(f"{m}: {e}")
            continue
        if found:
            return found, m, ""
    return [], "", "; ".join(errs)


def choose_target(matches, st, anchors=()):
    """Sort matches top-to-bottom, left-to-right and pick one."""
    ms = sorted(matches, key=lambda m: (round(m["rect"][1] / 12),
                                        m["rect"][0]))
    if not ms:
        return None, ms

    def ctr(m):
        l, t, r, b = m["rect"]
        return (l + r) / 2, (t + b) / 2

    which = st.get("which", "first")
    if which == "last":
        return ms[-1], ms
    if which == "number":
        k = int(fnum(st.get("n", 1), 1))
        return (ms[k - 1] if 1 <= k <= len(ms) else None), ms
    if which == "nearest":
        nx, ny = fnum(st.get("nx", 0)), fnum(st.get("ny", 0))
        return min(ms, key=lambda m: (ctr(m)[0] - nx) ** 2 +
                   (ctr(m)[1] - ny) ** 2), ms
    if which == "next to word":
        if not anchors:
            return None, ms

        def dist(m):
            cx, cy = ctr(m)
            return min(abs(cy - ctr(a)[1]) * 3 + abs(cx - ctr(a)[0])
                       for a in anchors)
        return min(ms, key=dist), ms
    return ms[0], ms


def find_targets(st):
    """Search the screen for the step's keyword.
    Returns (target or None, all matches in order, source, error)."""
    area = find_area(st)
    whole = st.get("whole", True)
    mode, kw = st.get("fmode", "contains"), st.get("keyword", "")
    method = st.get("method", "auto")

    def work():
        ms, src, err = _find_raw(method, mode, kw, area, whole)
        anchors = []
        if ms and st.get("which") == "next to word" and st.get("near"):
            anchors, _, _ = _find_raw(method, "contains", st["near"], area,
                                      whole)
        return ms, src, err, anchors

    try:
        ms, src, err, anchors = run_com(work)
    except Exception as e:
        return None, [], "", str(e)
    target, ordered = choose_target(ms, st, anchors)
    return target, ordered, src, err


def find_rule_text(st):
    w = st.get("which", "first")
    if w == "number":
        w = f"#{int(fnum(st.get('n', 1), 1))}"
    elif w == "next to word":
        w = f"next to \u201c{st.get('near', '')}\u201d"
    return (f"find {st.get('fmode', 'contains')} \u201c{st.get('keyword', '')}"
            f"\u201d · {w}" + ("" if st.get("whole", True) else " · in area"))


def show_find_overlay(root, matches, target, secs=4.0):
    """Draw numbered boxes on every match (target in green) for a while."""
    x0, y0, w, h = virtual_screen()
    key = "#ff00fe"
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.attributes("-topmost", True)
    try:
        ov.attributes("-transparentcolor", key)
    except Exception:
        pass
    ov.geometry(f"{w}x{h}+{x0}+{y0}")
    c = tk.Canvas(ov, bg=key, highlightthickness=0)
    c.pack(fill="both", expand=True)
    for k, m in enumerate(matches, 1):
        l, t, r, b = m["rect"]
        hit = m is target
        col = "#00c853" if hit else "#ff1744"
        c.create_rectangle(l - x0 - 3, t - y0 - 3, r - x0 + 3, b - y0 + 3,
                           outline=col, width=4 if hit else 3)
        c.create_rectangle(l - x0 - 3, t - y0 - 26, l - x0 + (110 if hit
                                                              else 30),
                           t - y0 - 3, fill=col, outline=col)
        c.create_text(l - x0 + 2, t - y0 - 15, anchor="w", fill="white",
                      font=(FONT, 11, "bold"),
                      text=f"{k}  ✔ click" if hit else str(k))
    ov.after(int(secs * 1000), ov.destroy)
    return ov


def text_matches(st, text):
    """Does text satisfy the step's rule?"""
    mode = st.get("mmode", "contains")
    pat = st.get("pattern", "")
    text = text or ""
    if mode == "contains":
        return pat.lower() in text.lower() if pat else bool(text.strip())
    if mode == "equals":
        return " ".join(text.split()).lower() == " ".join(pat.split()).lower()
    if mode == "regex":
        try:
            return re.search(pat, text, re.I) is not None
        except re.error:
            return False
    if mode == "number":
        m = NUM_RE.search(text)
        if not m:
            return False
        try:
            v = float(m.group().replace(",", ""))
        except ValueError:
            return False
        n = fnum(st.get("num", 0))
        op = st.get("op", "=")
        return {"=": v == n, ">": v > n, "<": v < n, "≥": v >= n,
                "≤": v <= n}.get(op, False)
    return False


def all_steps(steps):
    """Every step, including the sub-steps inside groups."""
    for st in steps:
        yield st
        if st.get("type") == "group":
            yield from all_steps(st.get("steps", []))


def set_clipboard_text(text):
    """Put Unicode text on the Windows clipboard (works from any thread)."""
    from ctypes import wintypes as wt
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [wt.HWND]
    u.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
    u.SetClipboardData.restype = wt.HANDLE
    k.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wt.HGLOBAL
    k.GlobalLock.argtypes = [wt.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wt.HGLOBAL]
    data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode(
        "utf-16-le") + b"\0\0"
    for _ in range(20):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("clipboard is busy")
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
        ptr = k.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        k.GlobalUnlock(h)
        u.SetClipboardData(13, h)                      # CF_UNICODETEXT
    finally:
        u.CloseClipboard()


def pair_matches(mode, find, text):
    text = text or ""
    if mode == "equals":
        return " ".join(text.split()).lower() == " ".join(find.split()).lower()
    if mode == "regex":
        try:
            return re.search(find, text, re.I) is not None
        except re.error:
            return False
    return find.lower() in text.lower() if find else bool(text.strip())


def fill_placeholders(paste, read_text):
    m = NUM_RE.search(read_text or "")
    return (paste.replace("{read}", (read_text or "").strip())
            .replace("{number}", m.group().replace(",", "") if m else ""))


ACTIONS = ["Continue", "Go to step", "Next loop", "Stop", "Next sequence",
           "Go to sequence", "Run sequence & return"]
WHEN_DONE = ["Stop", "Next sequence", "Go to sequence"]


def rule_text(st):
    mm = st.get("mmode", "contains")
    if mm == "number":
        return f"number {st.get('op', '=')} {fmt(st.get('num', 0))}"
    pat = st.get("pattern", "")
    if mm == "contains" and not pat:
        return "any text"
    return f"{mm} \u201c{pat}\u201d"


def action_text(st, ok):
    a = st.get("on_yes" if ok else "on_no", "Continue")
    if a == "Go to step":
        return f"go to step {st.get('yes_step' if ok else 'no_step', 1)}"
    if a == "Go to sequence":
        return f"go to \u201c{st.get('yes_seq' if ok else 'no_seq', '?')}\u201d"
    if a == "Run sequence & return":
        return (f"run \u201c{st.get('yes_seq' if ok else 'no_seq', '?')}"
                f"\u201d & come back")
    return a.lower()


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

    def chain(self):
        """This dialog, the dialogs under it, and the main window."""
        wins, w = [self], self.parent
        while w is not None:
            wins.append(w)
            w = w.parent if isinstance(w, Dialog) else None
        return wins

    def pick_into(self, xvar, yvar):
        self.grab_release()
        wins = self.chain()

        def done(x, y):
            if x is not None:
                xvar.set(str(int(x)))
                yvar.set(str(int(y)))
            for w in reversed(wins[1:]):
                w.deiconify()
            self.deiconify()
            self.lift()
            self.grab_set()

        pick_on_screen(wins[-1], done, hide=wins)

    def draw_box_into(self, xv, yv, awv, ahv, after=None):
        """Drag a box on screen; store its centre and size."""
        self.grab_release()
        wins = self.chain()

        def done(box):
            if box:
                l, t, r, b = box
                xv.set(str(int((l + r) / 2)))
                yv.set(str(int((t + b) / 2)))
                awv.set(str(int(r - l)))
                ahv.set(str(int(b - t)))
                if after:
                    after()
            for w in reversed(wins[1:]):
                w.deiconify()
            self.deiconify()
            self.lift()
            self.grab_set()

        draw_box_on_screen(wins[-1], done, hide=wins)

    def show_box(self, xv, yv, awv, ahv):
        cx, cy = fnum(xv.get()), fnum(yv.get())
        aw, ah = fnum(awv.get(), 300), fnum(ahv.get(), 60)
        wins = self.chain()
        for w in wins:
            w.withdraw()
        show_box_overlay(wins[-1], (cx - aw / 2, cy - ah / 2, cx + aw / 2,
                                    cy + ah / 2), 2.5)

        def back():
            for w in reversed(wins):
                w.deiconify()
            self.lift()

        self.after(2600, back)

    def box_buttons(self, master, after=None, size=12):
        """[ ▭ Draw box ] [ 👁 Show box ] row bound to x/y/aw/ah."""
        row = tk.Frame(master, bg=self.BG)
        big_button(row, "▭  Draw box on screen",
                   lambda: self.draw_box_into(self.x, self.y, self.aw,
                                              self.ah, after),
                   bg="#6a1b9a", abg="#8e24aa", size=size, pady=8
                   ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        soft_button(row, "👁 Show box",
                    lambda: self.show_box(self.x, self.y, self.aw, self.ah),
                    size=size - 1).pack(side="left")
        return row

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


class SeqPicker(Dialog):
    """Tap one sequence name."""

    def __init__(self, parent, names, current=""):
        super().__init__(parent, "Choose sequence")
        self.var = tk.StringVar(value=current if current in names
                                else (names[0] if names else ""))
        self.label(self.body, "Tap a sequence:").pack(anchor="w")
        if names:
            Choice(self.body, self.var, names, cols=2, size=12
                   ).pack(fill="x", pady=4)
        else:
            self.label(self.body, "(no other sequences yet - make one in "
                                  "My sequences)", bold=False).pack()
        self.footer()

    def ok(self):
        self.result = self.var.get()
        self.destroy()


def seq_chooser(master, var, names, dialog_parent):
    """Button showing the chosen sequence; tap to choose another."""
    b = soft_button(master, "", None, size=12)

    def draw(*a):
        b.config(text=f"📂  {var.get() or '(choose)'}   ▾")

    def pick():
        lst = names() if callable(names) else list(names)
        r = SeqPicker(dialog_parent, lst, var.get()).run()
        if r:
            var.set(r)

    b.config(command=pick)
    var.trace_add("write", draw)
    draw()
    return b


class StepDialog(Dialog):
    """Add / edit one sequence step."""

    def __init__(self, parent, step, seq_names=()):
        super().__init__(parent, "Step")
        s = dict(step)
        self.seq_names = list(seq_names)
        self.type = tk.StringVar(value={"click": "🖱 Click", "key": "⌨ Key",
                                        "link": "🔗 Link", "wait": "⏱ Wait",
                                        "read": "🔍 Read",
                                        "paste": "📋 Paste",
                                        "group": "🗂 Group",
                                        "find": "🎯 Find"}[s.get("type",
                                                                "click")])
        self.f_kw = tk.StringVar(value=s.get("keyword", ""))
        self.f_mode = tk.StringVar(value={"equals": "Equals",
                                          "regex": "Regex"}.get(
            s.get("fmode"), "Contains"))
        self.f_whole = tk.BooleanVar(value=s.get("whole", True))
        self.f_which = tk.StringVar(value={
            "last": "Last", "number": "Number", "nearest": "Nearest to spot",
            "next to word": "Next to word"}.get(s.get("which"), "First"))
        self.f_n = tk.StringVar(value=str(s.get("n", 1)))
        self.nx = tk.StringVar(value=str(s.get("nx", 0)))
        self.ny = tk.StringVar(value=str(s.get("ny", 0)))
        self.f_near = tk.StringVar(value=s.get("near", ""))
        self.f_dx = tk.StringVar(value=str(s.get("dx", 0)))
        self.f_dy = tk.StringVar(value=str(s.get("dy", 0)))
        self.f_test = tk.StringVar(value="")
        self.yes_title = tk.StringVar(value="✔ If it matches:")
        self.no_title = tk.StringVar(value="✖ If not:")
        self.g_steps = json.loads(json.dumps(s.get("steps", [])))
        self.p_click = tk.BooleanVar(value=s.get("click_first", True))
        self.cx = tk.StringVar(value=str(s.get("cx", 0)))
        self.cy = tk.StringVar(value=str(s.get("cy", 0)))
        self.p_source = tk.StringVar(
            value="Pick by reading screen" if s.get("source") == "ocr"
            else "Same text every time")
        self.p_text0 = s.get("text", "")
        self.p_mode = tk.StringVar(value={"equals": "Equals",
                                          "regex": "Regex"}.get(
            s.get("pmode"), "Contains"))
        self.p_pairs0 = [dict(pr) for pr in s.get("pairs", [])]
        self.p_nomatch = tk.StringVar(value={"skip": "Skip",
                                             "stop": "Stop"}.get(
            s.get("nomatch"), "Paste default"))
        self.p_default = tk.StringVar(value=s.get("default", ""))
        self.p_enter = tk.BooleanVar(value=s.get("enter", False))
        self.p_how = tk.StringVar(value="Type letters"
                                  if s.get("how") == "type"
                                  else "Paste (Ctrl+V)")
        self.aw = tk.StringVar(value=fmt(s.get("aw", 300)))
        self.ah = tk.StringVar(value=fmt(s.get("ah", 60)))
        self.method = tk.StringVar(value={"uia": "Windows text",
                                          "ocr": "OCR (picture)"}.get(
            s.get("method"), "Auto"))
        self.mmode = tk.StringVar(value={"equals": "Equals", "regex": "Regex",
                                         "number": "Number"}.get(
            s.get("mmode"), "Contains"))
        self.pattern = tk.StringVar(value=s.get("pattern", ""))
        self.op = tk.StringVar(value=s.get("op", "≥"))
        self.num = tk.StringVar(value=fmt(s.get("num", 0)))
        self.timeout = tk.StringVar(value=fmt(s.get("timeout", 0)))
        self.on_yes = tk.StringVar(value=s.get("on_yes", "Continue"))
        self.yes_step = tk.StringVar(value=str(s.get("yes_step", 1)))
        self.on_no = tk.StringVar(value=s.get("on_no", "Stop"))
        self.no_step = tk.StringVar(value=str(s.get("no_step", 1)))
        first = self.seq_names[0] if self.seq_names else ""
        self.yes_seq = tk.StringVar(value=s.get("yes_seq", first))
        self.no_seq = tk.StringVar(value=s.get("no_seq", first))
        self.read_result = tk.StringVar(value="")
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
        Choice(b, self.type, ["🖱 Click", "⌨ Key", "🔗 Link", "⏱ Wait",
                              "🔍 Read", "📋 Paste", "🗂 Group", "🎯 Find"],
               cols=4, size=11).pack(fill="x", pady=(4, 10))

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

        # --- read panel
        rd = self.read_panel = tk.Frame(self.area, bg=self.BG)
        self.box_buttons(rd).pack(fill="x")
        soft_button(rd, "📍 or pick just a point (centre)",
                    lambda: self.pick_into(self.x, self.y), size=11
                    ).pack(anchor="w", pady=(4, 0))
        xy2 = tk.Frame(rd, bg=self.BG)
        xy2.pack(anchor="w", pady=6)
        self.label(xy2, "X ").pack(side="left")
        NumField(xy2, self.x, step=1, maxv=99999).pack(side="left")
        self.label(xy2, "   Y ").pack(side="left")
        NumField(xy2, self.y, step=1, maxv=99999).pack(side="left")
        ar = tk.Frame(rd, bg=self.BG)
        ar.pack(anchor="w", pady=(0, 6))
        self.label(ar, "Area (for OCR)  W ").pack(side="left")
        NumField(ar, self.aw, step=20, minv=20, maxv=2000).pack(side="left")
        self.label(ar, "  H ").pack(side="left")
        NumField(ar, self.ah, step=10, minv=10, maxv=1200).pack(side="left")
        self.label(rd, "Read with:").pack(anchor="w")
        Choice(rd, self.method, ["Auto", "Windows text", "OCR (picture)"],
               cols=3).pack(fill="x", pady=(2, 6))
        tr = tk.Frame(rd, bg=self.BG)
        tr.pack(fill="x", pady=(0, 8))
        soft_button(tr, "🔍 Test read now", self.test_read
                    ).pack(side="left")
        tk.Label(tr, textvariable=self.read_result, bg=self.BG, fg="#0d47a1",
                 font=(FONT, sz(11)), wraplength=sz(330), justify="left",
                 anchor="w").pack(side="left", padx=8, fill="x", expand=True)

        self.label(rd, "Text must:").pack(anchor="w")
        Choice(rd, self.mmode, ["Contains", "Equals", "Regex", "Number"],
               cols=4).pack(fill="x", pady=(2, 4))
        self.pat_row = tk.Frame(rd, bg=self.BG)
        pe = tk.Entry(self.pat_row, textvariable=self.pattern,
                      font=(FONT, sz(14)), relief="solid", bd=1)
        pe.pack(side="left", fill="x", expand=True, ipady=sz(6))
        soft_button(self.pat_row, "⌨",
                    lambda: (pe.focus_set(), open_touch_keyboard()),
                    size=13, padx=12, pady=4).pack(side="left", padx=(6, 0))
        self.num_row = tk.Frame(rd, bg=self.BG)
        Choice(self.num_row, self.op, ["=", ">", "<", "≥", "≤"], cols=5
               ).pack(side="left")
        NumField(self.num_row, self.num, step=1, minv=-1e12, maxv=1e12,
                 width=8).pack(side="left", padx=(8, 0))
        self.hint = self.label(rd, "", size=10, bold=False, fg="#666")
        self.after_match = tk.Frame(self.area, bg=self.BG)
        tm = tk.Frame(self.after_match, bg=self.BG)
        tm.pack(anchor="w", pady=(6, 0))
        self.label(tm, "Keep checking for up to ").pack(side="left")
        NumField(tm, self.timeout, step=1, maxv=3600, width=4
                 ).pack(side="left")
        self.label(tm, " sec").pack(side="left")
        for title, var, stepv, seqv in (
                (self.yes_title, self.on_yes, self.yes_step, self.yes_seq),
                (self.no_title, self.on_no, self.no_step, self.no_seq)):
            tl = self.label(self.after_match, "")
            tl.config(textvariable=title)
            tl.pack(anchor="w", pady=(8, 0))
            row = tk.Frame(self.after_match, bg=self.BG)
            row.pack(fill="x")
            Choice(row, var, ACTIONS, cols=3, size=11).pack(fill="x")
            sr = tk.Frame(self.after_match, bg=self.BG)
            self.label(sr, "   step number: ", bold=False).pack(side="left")
            NumField(sr, stepv, step=1, minv=1, maxv=999, width=4
                     ).pack(side="left")
            qr = tk.Frame(self.after_match, bg=self.BG)
            self.label(qr, "   sequence: ", bold=False).pack(side="left")
            seq_chooser(qr, seqv, self.seq_names, self).pack(
                side="left", fill="x", expand=True)
            var.trace_add("write", lambda *a, v=var, f=sr, q=qr, r=row:
                          self._show_goto(v, f, q, r))
            self._show_goto(var, sr, qr, row)
        self.mmode.trace_add("write", lambda *a: self._show_match())
        self._show_match()

        # --- find & click panel
        fp = self.find_panel = tk.Frame(self.area, bg=self.BG)
        self.label(fp, "Find this word / button:").pack(anchor="w")
        kr = tk.Frame(fp, bg=self.BG)
        kr.pack(fill="x", pady=(2, 4))
        ke = tk.Entry(kr, textvariable=self.f_kw, font=(FONT, sz(14)),
                      relief="solid", bd=1)
        ke.pack(side="left", fill="x", expand=True, ipady=sz(6))
        soft_button(kr, "⌨", lambda: (ke.focus_set(), open_touch_keyboard()),
                    size=13, padx=12, pady=4).pack(side="left", padx=(6, 0))
        Choice(fp, self.f_mode, ["Contains", "Equals", "Regex"], cols=3,
               size=11).pack(fill="x", pady=(0, 2))
        self.label(fp, "Tip: Equals is best for short button words like "
                       "\u201cBack\u201d.", size=10, bold=False,
                   fg="#666").pack(anchor="w")
        self.box_buttons(fp, after=lambda: self.f_whole.set(False)
                         ).pack(fill="x", pady=(8, 4))
        Toggle(fp, "Search the whole screen", self.f_whole
               ).pack(fill="x")
        self.f_area = tk.Frame(fp, bg=self.BG)
        soft_button(self.f_area, "📍 Pick centre of search box",
                    lambda: self.pick_into(self.x, self.y)).pack(anchor="w")
        ar2 = tk.Frame(self.f_area, bg=self.BG)
        ar2.pack(anchor="w", pady=(4, 0))
        self.label(ar2, "X ").pack(side="left")
        NumField(ar2, self.x, step=1, maxv=99999, width=5).pack(side="left")
        self.label(ar2, " Y ").pack(side="left")
        NumField(ar2, self.y, step=1, maxv=99999, width=5).pack(side="left")
        ar3 = tk.Frame(self.f_area, bg=self.BG)
        ar3.pack(anchor="w", pady=(4, 0))
        self.label(ar3, "Box W ").pack(side="left")
        NumField(ar3, self.aw, step=50, minv=20, maxv=8000, width=5
                 ).pack(side="left")
        self.label(ar3, " H ").pack(side="left")
        NumField(ar3, self.ah, step=50, minv=10, maxv=5000, width=5
                 ).pack(side="left")
        self.f_whole.trace_add("write", lambda *a: self._show_find())
        self.f_after_area = tk.Frame(fp, bg=self.BG)
        self.f_after_area.pack(fill="x")
        fa = self.f_after_area
        self.label(fa, "Read with:").pack(anchor="w", pady=(6, 0))
        Choice(fa, self.method, ["Auto", "Windows text", "OCR (picture)"],
               cols=3, size=11).pack(fill="x", pady=(2, 4))
        self.label(fa, "If it finds more than one, click:").pack(anchor="w")
        Choice(fa, self.f_which, ["First", "Last", "Number",
                                  "Nearest to spot", "Next to word"],
               cols=3, size=11).pack(fill="x", pady=(2, 2))
        self.f_num_row = tk.Frame(fa, bg=self.BG)
        self.label(self.f_num_row, "   number (from top, left to right): ",
                   bold=False).pack(side="left")
        NumField(self.f_num_row, self.f_n, step=1, minv=1, maxv=99, width=3
                 ).pack(side="left")
        self.f_near_row = tk.Frame(fa, bg=self.BG)
        soft_button(self.f_near_row, "📍 Pick the spot",
                    lambda: self.pick_into(self.nx, self.ny)).pack(side="left")
        self.label(self.f_near_row, "  X ").pack(side="left")
        NumField(self.f_near_row, self.nx, step=1, maxv=99999, width=5
                 ).pack(side="left")
        self.label(self.f_near_row, " Y ").pack(side="left")
        NumField(self.f_near_row, self.ny, step=1, maxv=99999, width=5
                 ).pack(side="left")
        self.f_word_row = tk.Frame(fa, bg=self.BG)
        self.label(self.f_word_row, "   next to: ").pack(side="left")
        tk.Entry(self.f_word_row, textvariable=self.f_near,
                 font=(FONT, sz(13)), relief="solid", bd=1
                 ).pack(side="left", fill="x", expand=True, ipady=sz(5))
        self.f_which.trace_add("write", lambda *a: self._show_find())
        self.f_click_lbl = self.label(fa, "Click:")
        self.f_click_lbl.pack(anchor="w", pady=(8, 0))
        Choice(fa, self.btn, CLICK_TYPES, cols=3, size=11
               ).pack(fill="x", pady=(2, 2))
        off = tk.Frame(fa, bg=self.BG)
        off.pack(anchor="w", pady=(2, 0))
        self.label(off, "Offset  X ").pack(side="left")
        NumField(off, self.f_dx, step=10, minv=-2000, maxv=2000, width=4
                 ).pack(side="left")
        self.label(off, "  Y ").pack(side="left")
        NumField(off, self.f_dy, step=10, minv=-2000, maxv=2000, width=4
                 ).pack(side="left")
        tf = tk.Frame(fa, bg=self.BG)
        tf.pack(fill="x", pady=(8, 0))
        soft_button(tf, "🔍 Test find (shows boxes)", self.test_find
                    ).pack(side="left")
        tk.Label(fa, textvariable=self.f_test, bg=self.BG, fg="#0d47a1",
                 font=(FONT, sz(11)), wraplength=sz(440), justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))
        self._show_find()

        # --- group panel (sub-steps)
        gp = self.group_panel = tk.Frame(self.area, bg=self.BG)
        self.label(gp, "Sub-steps (run top to bottom, each with all step "
                       "features):", size=11).pack(anchor="w")
        gf = tk.Frame(gp, bg=self.BG)
        gf.pack(fill="x", pady=4)
        self.gtree = ttk.Treeview(gf, columns=("n", "name", "step", "wait"),
                                  show="headings", height=4,
                                  selectmode="browse")
        for c, t_, w_, a_ in (("n", "#", 34, "center"),
                              ("name", "Name", 90, "w"),
                              ("step", "Step", 230, "w"),
                              ("wait", "Then wait", 80, "center")):
            self.gtree.heading(c, text=t_)
            self.gtree.column(c, width=sz(w_), anchor=a_,
                              stretch=(a_ == "w"))
        gsb = ttk.Scrollbar(gf, orient="vertical", command=self.gtree.yview)
        self.gtree.configure(yscrollcommand=gsb.set)
        self.gtree.pack(side="left", fill="x", expand=True)
        gsb.pack(side="right", fill="y")
        self.gtree.bind("<Double-1>", lambda e: self.g_edit())
        big_button(gp, "➕  Add sub-step", self.g_add, bg=GREEN, abg=GREEN_A,
                   size=12, pady=8).pack(fill="x", pady=(2, 4))
        gb = tk.Frame(gp, bg=self.BG)
        gb.pack(fill="x", pady=(0, 6))
        for k_, (t_, cmd) in enumerate((("✏ Edit", self.g_edit),
                                        ("🗑 Delete", self.g_delete),
                                        ("▲ Up", lambda: self.g_move(-1)),
                                        ("▼ Down", lambda: self.g_move(1)),
                                        ("⧉ Copy", self.g_copy))):
            soft_button(gb, t_, cmd, size=10, padx=3).grid(
                row=0, column=k_, sticky="ew", padx=2)
            gb.columnconfigure(k_, weight=1, uniform="g")
        self.label(gp, "Inside a group, a Read step's \u201cGo to step\u201d "
                       "means a sub-step number.", size=10, bold=False,
                   fg="#666").pack(anchor="w")
        self.g_refresh()

        # --- paste panel
        pp = self.paste_panel = tk.Frame(self.area, bg=self.BG)
        self.p_toggle = Toggle(pp, "Click a spot first (e.g. the text box)",
                               self.p_click)
        self.p_toggle.pack(fill="x")
        self.p_click_row = tk.Frame(pp, bg=self.BG)
        soft_button(self.p_click_row, "📍 Pick spot to click",
                    lambda: self.pick_into(self.cx, self.cy)
                    ).pack(side="left")
        self.label(self.p_click_row, "  X ").pack(side="left")
        NumField(self.p_click_row, self.cx, step=1, maxv=99999, width=5
                 ).pack(side="left")
        self.label(self.p_click_row, " Y ").pack(side="left")
        NumField(self.p_click_row, self.cy, step=1, maxv=99999, width=5
                 ).pack(side="left")
        self.p_click.trace_add("write", lambda *a: self._show_paste())

        self.label(pp, "What to paste:").pack(anchor="w", pady=(8, 0))
        Choice(pp, self.p_source, ["Same text every time",
                                   "Pick by reading screen"], cols=2
               ).pack(fill="x", pady=(2, 6))
        self.p_source.trace_add("write", lambda *a: self._show_paste())

        self.p_fixed = tk.Frame(pp, bg=self.BG)
        self.p_textbox = tk.Text(self.p_fixed, height=3, font=(FONT, sz(13)),
                                 relief="solid", bd=1, wrap="word")
        self.p_textbox.insert("1.0", self.p_text0)
        self.p_textbox.pack(fill="x")

        self.p_ocr = tk.Frame(pp, bg=self.BG)
        self.box_buttons(self.p_ocr).pack(fill="x")
        soft_button(self.p_ocr, "📍 or pick just a point (centre)",
                    lambda: self.pick_into(self.x, self.y), size=11
                    ).pack(anchor="w", pady=(4, 0))
        r1 = tk.Frame(self.p_ocr, bg=self.BG)
        r1.pack(anchor="w", pady=4)
        self.label(r1, "X ").pack(side="left")
        NumField(r1, self.x, step=1, maxv=99999, width=5).pack(side="left")
        self.label(r1, "  Y ").pack(side="left")
        NumField(r1, self.y, step=1, maxv=99999, width=5).pack(side="left")
        r2 = tk.Frame(self.p_ocr, bg=self.BG)
        r2.pack(anchor="w", pady=(0, 4))
        self.label(r2, "Area W ").pack(side="left")
        NumField(r2, self.aw, step=20, minv=20, maxv=2000, width=4
                 ).pack(side="left")
        self.label(r2, "  H ").pack(side="left")
        NumField(r2, self.ah, step=10, minv=10, maxv=1200, width=4
                 ).pack(side="left")
        Choice(self.p_ocr, self.method, ["Auto", "Windows text",
                                         "OCR (picture)"], cols=3, size=11
               ).pack(fill="x", pady=(0, 4))
        self.label(self.p_ocr, "Pairs: if the text …  →  paste:"
                   ).pack(anchor="w", pady=(4, 0))
        Choice(self.p_ocr, self.p_mode, ["Contains", "Equals", "Regex"],
               cols=3, size=11).pack(fill="x", pady=(2, 4))
        self.pairs_box = tk.Frame(self.p_ocr, bg=self.BG)
        self.pairs_box.pack(fill="x")
        self.pair_rows = []
        for pr in self.p_pairs0 or [{"find": "", "paste": ""}]:
            self.add_pair(pr.get("find", ""), pr.get("paste", ""))
        pr_btns = tk.Frame(self.p_ocr, bg=self.BG)
        pr_btns.pack(fill="x", pady=(4, 0))
        soft_button(pr_btns, "➕ Add pair", lambda: self.add_pair()
                    ).pack(side="left")
        soft_button(pr_btns, "🔍 Test read", self.test_paste_read
                    ).pack(side="left", padx=6)
        self.p_test = tk.StringVar(value="")
        tk.Label(self.p_ocr, textvariable=self.p_test, bg=self.BG,
                 fg="#0d47a1", font=(FONT, sz(11)), wraplength=sz(440),
                 justify="left", anchor="w").pack(fill="x", pady=(4, 0))
        self.label(self.p_ocr, "If nothing matches:").pack(anchor="w",
                                                          pady=(6, 0))
        Choice(self.p_ocr, self.p_nomatch, ["Paste default", "Skip", "Stop"],
               cols=3, size=11).pack(fill="x", pady=(2, 4))
        self.p_def_row = tk.Frame(self.p_ocr, bg=self.BG)
        self.label(self.p_def_row, "Default: ").pack(side="left")
        tk.Entry(self.p_def_row, textvariable=self.p_default,
                 font=(FONT, sz(13)), relief="solid", bd=1
                 ).pack(side="left", fill="x", expand=True, ipady=sz(5))
        self.p_nomatch.trace_add("write", lambda *a: self._show_paste())
        self.p_tip = self.label(self.p_ocr, "Tip: {read} = the text it read, "
                                            "{number} = first number in it",
                                size=10, bold=False, fg="#666")
        self.p_tip.pack(anchor="w")

        self.p_after = tk.Frame(pp, bg=self.BG)
        self.p_after.pack(fill="x", pady=(8, 0))
        Toggle(self.p_after, "Press Enter after pasting", self.p_enter
               ).pack(fill="x")
        hr = tk.Frame(self.p_after, bg=self.BG)
        hr.pack(fill="x", pady=(6, 0))
        self.label(hr, "How:  ").pack(side="left")
        Choice(hr, self.p_how, ["Paste (Ctrl+V)", "Type letters"], cols=2,
               size=11).pack(side="left", fill="x", expand=True)
        self._show_paste()

        # --- then wait (all)
        self.after_panel = self.wait_row(b, self.amin, self.amax,
                                         "Then wait before next step (sec):")
        self.after_panel.pack(anchor="w", pady=(12, 0))

        self.type.trace_add("write", lambda *a: self.show())
        self.show()
        self.footer()

    def kind(self):
        return {"🖱 Click": "click", "⌨ Key": "key", "🔗 Link": "link",
                "⏱ Wait": "wait", "🔍 Read": "read",
                "📋 Paste": "paste", "🗂 Group": "group",
                "🎯 Find": "find"}[self.type.get()]

    def _show_goto(self, var, frame, qframe, after):
        frame.pack_forget()
        qframe.pack_forget()
        if var.get() == "Go to step":
            frame.pack(after=after, anchor="w", pady=(4, 0))
        elif var.get() in ("Go to sequence", "Run sequence & return"):
            qframe.pack(after=after, fill="x", pady=(4, 0))

    def _show_find(self):
        if not hasattr(self, "f_after_area"):
            return
        if self.f_whole.get():
            self.f_area.pack_forget()
        else:
            self.f_area.pack(fill="x", pady=(4, 0), before=self.f_after_area)
        for r in (self.f_num_row, self.f_near_row, self.f_word_row):
            r.pack_forget()
        w = self.f_which.get()
        row = {"Number": self.f_num_row, "Nearest to spot": self.f_near_row,
               "Next to word": self.f_word_row}.get(w)
        if row:
            row.pack(fill="x", pady=(2, 0), before=self.f_click_lbl)

    def _find_step(self):
        return {"keyword": self.f_kw.get().strip(),
                "fmode": self.f_mode.get().lower(),
                "whole": self.f_whole.get(),
                "x": int(fnum(self.x.get())), "y": int(fnum(self.y.get())),
                "aw": int(fnum(self.aw.get(), 300)),
                "ah": int(fnum(self.ah.get(), 60)),
                "method": {"Windows text": "uia",
                           "OCR (picture)": "ocr"}.get(self.method.get(),
                                                       "auto"),
                "which": {"Last": "last", "Number": "number",
                          "Nearest to spot": "nearest",
                          "Next to word": "next to word"}.get(
                    self.f_which.get(), "first"),
                "n": max(1, int(fnum(self.f_n.get(), 1))),
                "nx": int(fnum(self.nx.get())), "ny": int(fnum(self.ny.get())),
                "near": self.f_near.get().strip(),
                "button": self.btn.get(),
                "dx": int(fnum(self.f_dx.get())),
                "dy": int(fnum(self.f_dy.get()))}

    def test_find(self):
        fs = self._find_step()
        if not fs["keyword"]:
            self.f_test.set("Type a word first")
            return
        wins = self.chain()
        for w in wins:
            w.withdraw()
        self.update()
        time.sleep(0.35)
        target, ms, src, err = find_targets(fs)

        def back():
            for w in reversed(wins):
                w.deiconify()
            self.lift()

        if ms:
            show_find_overlay(self.parent if not isinstance(self.parent,
                                                            Dialog)
                              else wins[-1], ms, target, 3.5)
            self.after(3600, back)
        else:
            back()
        src = {"uia": "Windows text", "ocr": "OCR"}.get(src, src)
        if not ms:
            self.f_test.set("Not found" + (f" ({err[:120]})" if err else ""))
        elif target is None:
            self.f_test.set(f"Found {len(ms)} [{src}], but none fits your "
                            f"choice (e.g. number too big / word not found)")
        else:
            k = ms.index(target) + 1
            l, t, r, b = target["rect"]
            self.f_test.set(
                f"Found {len(ms)} [{src}] → will click #{k} "
                f"\u201c{target['text'][:40]}\u201d at "
                f"({int((l + r) / 2) + fs['dx']}, {int((t + b) / 2) + fs['dy']})")

    def _show_match(self):
        self.pat_row.pack_forget()
        self.num_row.pack_forget()
        m = self.mmode.get()
        hints = {"Contains": "Matches if the text has this word/phrase "
                             "(empty = any text).",
                 "Equals": "Matches only if the text is exactly this.",
                 "Regex": "Pattern, e.g.  ^Score\\s*\\d+   or   "
                          "done|finished",
                 "Number": "Uses the first number found in the text."}
        self.hint.config(text=hints.get(m, ""))
        self.hint.pack(anchor="w")
        if m == "Number":
            self.num_row.pack(anchor="w", pady=(2, 0), before=self.hint)
        else:
            self.pat_row.pack(fill="x", pady=(2, 0), before=self.hint)

    def _read_rule(self):
        return {"mmode": self.mmode.get().lower(),
                "pattern": self.pattern.get(), "op": self.op.get(),
                "num": fnum(self.num.get())}

    def test_read(self):
        method = {"Windows text": "uia", "OCR (picture)": "ocr"}.get(
            self.method.get(), "auto")
        rule = self._read_rule()
        wins = self.chain()
        for w in wins:
            w.withdraw()
        self.update()
        time.sleep(0.35)
        text, src, err = read_screen_text(
            method, fnum(self.x.get()), fnum(self.y.get()),
            fnum(self.aw.get(), 300), fnum(self.ah.get(), 60),
            want=lambda t: text_matches(rule, t))
        for w in wins:
            w.deiconify()
        self.lift()
        if text:
            ok = text_matches(rule, text)
            src = {"uia": "Windows text", "ocr": "OCR"}.get(src, src)
            self.read_result.set(f"[{src}] \u201c{text[:120]}\u201d  →  "
                                 + ("✔ matches" if ok else "✖ no match"))
        else:
            self.read_result.set("No text found" + (f" ({err})" if err
                                                     else ""))

    # ---- group sub-steps
    def g_refresh(self, select=None):
        self.gtree.delete(*self.gtree.get_children())
        for k, st in enumerate(self.g_steps):
            self.gtree.insert("", "end", iid=str(k), values=(
                k + 1, st.get("name", ""), describe(st),
                span(st.get("amin", 0), st.get("amax", 0)) + " s"))
        if select is not None and 0 <= select < len(self.g_steps):
            self.gtree.selection_set(str(select))
            self.gtree.see(str(select))

    def g_sel(self):
        sel = self.gtree.selection()
        return int(sel[0]) if sel else None

    def g_add(self):
        base = {"type": "click", "x": 0, "y": 0, "button": "Left",
                "times": 1, "tmin": 0.5, "tmax": 1, "amin": 0, "amax": 1}
        st = StepDialog(self, base, self.seq_names).run()
        if st:
            i = self.g_sel()
            pos = len(self.g_steps) if i is None else i + 1
            self.g_steps.insert(pos, st)
            self.g_refresh(pos)

    def g_edit(self):
        i = self.g_sel()
        if i is None:
            return
        st = StepDialog(self, self.g_steps[i], self.seq_names).run()
        if st:
            self.g_steps[i] = st
            self.g_refresh(i)

    def g_delete(self):
        i = self.g_sel()
        if i is not None:
            del self.g_steps[i]
            self.g_refresh(min(i, len(self.g_steps) - 1))

    def g_move(self, d):
        i = self.g_sel()
        if i is None:
            return
        j = i + d
        if 0 <= j < len(self.g_steps):
            self.g_steps[i], self.g_steps[j] = self.g_steps[j], self.g_steps[i]
            self.g_refresh(j)

    def g_copy(self):
        i = self.g_sel()
        if i is not None:
            self.g_steps.insert(i + 1, json.loads(json.dumps(self.g_steps[i])))
            self.g_refresh(i + 1)

    def add_pair(self, find="", paste=""):
        f = tk.Frame(self.pairs_box, bg=self.BG)
        f.pack(fill="x", pady=2)
        fv, pv = tk.StringVar(value=find), tk.StringVar(value=paste)
        tk.Entry(f, textvariable=fv, font=(FONT, sz(12)), relief="solid",
                 bd=1, width=12).pack(side="left", fill="x", expand=True,
                                      ipady=sz(5))
        self.label(f, " → ").pack(side="left")
        tk.Entry(f, textvariable=pv, font=(FONT, sz(12)), relief="solid",
                 bd=1, width=16).pack(side="left", fill="x", expand=True,
                                      ipady=sz(5))
        row = (f, fv, pv)

        def remove():
            f.destroy()
            if row in self.pair_rows:
                self.pair_rows.remove(row)

        soft_button(f, "✖", remove, size=11, padx=8, pady=3
                    ).pack(side="left", padx=(4, 0))
        self.pair_rows.append(row)

    def _pairs(self):
        return [{"find": fv.get(), "paste": pv.get()}
                for _, fv, pv in self.pair_rows
                if fv.get().strip() or pv.get().strip()]

    def _show_paste(self):
        if not hasattr(self, "p_after"):
            return
        self.p_click_row.pack_forget()
        self.p_fixed.pack_forget()
        self.p_ocr.pack_forget()
        if self.p_click.get():
            self.p_click_row.pack(fill="x", pady=(4, 0), after=self.p_toggle)
        if self.p_source.get().startswith("Pick"):
            self.p_ocr.pack(fill="x", before=self.p_after)
        else:
            self.p_fixed.pack(fill="x", before=self.p_after)
        if self.p_nomatch.get() == "Paste default":
            self.p_def_row.pack(fill="x", pady=(0, 4), before=self.p_tip)
        else:
            self.p_def_row.pack_forget()

    def test_paste_read(self):
        method = {"Windows text": "uia", "OCR (picture)": "ocr"}.get(
            self.method.get(), "auto")
        mode = self.p_mode.get().lower()
        pairs = self._pairs()
        wins = self.chain()
        for w in wins:
            w.withdraw()
        self.update()
        time.sleep(0.35)
        text, src, err = read_screen_text(
            method, fnum(self.x.get()), fnum(self.y.get()),
            fnum(self.aw.get(), 300), fnum(self.ah.get(), 60),
            want=lambda t: any(pair_matches(mode, p["find"], t)
                               for p in pairs))
        for w in wins:
            w.deiconify()
        self.lift()
        if not text:
            self.p_test.set("No text found" + (f" ({err})" if err else ""))
            return
        hit = next((p for p in pairs if pair_matches(mode, p["find"], text)),
                   None)
        res = (f"→ would paste \u201c{fill_placeholders(hit['paste'], text)}"
               f"\u201d" if hit else f"→ no pair matches "
               f"({self.p_nomatch.get().lower()})")
        self.p_test.set(f"Read: \u201c{text[:100]}\u201d  {res}")

    def show(self):
        for p in (self.click_panel, self.key_panel, self.repeat_panel,
                  self.link_panel, self.read_panel, self.paste_panel,
                  self.group_panel, self.find_panel, self.after_match):
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
        elif k == "read":
            self.read_panel.pack(fill="x")
            self.yes_title.set("✔ If it matches:")
            self.no_title.set("✖ If not:")
            self.after_match.pack(fill="x")
        elif k == "find":
            self.find_panel.pack(fill="x")
            self.yes_title.set("✔ If found (after clicking it):")
            self.no_title.set("✖ If not found:")
            self.after_match.pack(fill="x")
        elif k == "paste":
            self.paste_panel.pack(fill="x")
        elif k == "group":
            self.group_panel.pack(fill="x")
            self.repeat_panel.pack(fill="x")

    def ok(self):
        k = self.kind()
        amin, amax = sorted((max(0, fnum(self.amin.get())),
                             max(0, fnum(self.amax.get()))))
        st = {"type": k, "amin": amin, "amax": amax,
              "name": self.name.get().strip(),
              "run": ("once" if self.run_mode.get().startswith("Only")
                      else "every")}
        if k == "group":
            if not self.g_steps:
                messagebox.showerror("Step", "Add at least one sub-step",
                                     parent=self)
                return
            st["steps"] = self.g_steps
        if k in ("click", "key", "group"):
            tmin, tmax = sorted((max(0, fnum(self.tmin.get())),
                                 max(0, fnum(self.tmax.get()))))
            st.update(times=max(1, int(fnum(self.times.get(), 1))),
                      tmin=tmin, tmax=tmax)
        if k == "click":
            st.update(x=int(fnum(self.x.get())), y=int(fnum(self.y.get())),
                      button=self.btn.get())
        elif k == "key":
            st["key"] = self.key.get()
        elif k == "read":
            st.update(x=int(fnum(self.x.get())), y=int(fnum(self.y.get())),
                      aw=int(fnum(self.aw.get(), 300)),
                      ah=int(fnum(self.ah.get(), 60)),
                      method={"Windows text": "uia",
                              "OCR (picture)": "ocr"}.get(self.method.get(),
                                                          "auto"),
                      timeout=max(0, fnum(self.timeout.get())),
                      on_yes=self.on_yes.get(),
                      yes_step=max(1, int(fnum(self.yes_step.get(), 1))),
                      on_no=self.on_no.get(),
                      no_step=max(1, int(fnum(self.no_step.get(), 1))),
                      yes_seq=self.yes_seq.get(), no_seq=self.no_seq.get(),
                      **self._read_rule())
            if st["mmode"] == "regex":
                try:
                    re.compile(st["pattern"])
                except re.error as e:
                    messagebox.showerror("Step", f"Regex problem: {e}",
                                         parent=self)
                    return
        elif k == "find":
            st.update(self._find_step())
            st.update(timeout=max(0, fnum(self.timeout.get())),
                      on_yes=self.on_yes.get(),
                      yes_step=max(1, int(fnum(self.yes_step.get(), 1))),
                      on_no=self.on_no.get(),
                      no_step=max(1, int(fnum(self.no_step.get(), 1))),
                      yes_seq=self.yes_seq.get(), no_seq=self.no_seq.get())
            if not st["keyword"]:
                messagebox.showerror("Step", "Type the word to find",
                                     parent=self)
                return
            if st["fmode"] == "regex":
                try:
                    re.compile(st["keyword"])
                except re.error as e:
                    messagebox.showerror("Step", f"Regex problem: {e}",
                                         parent=self)
                    return
        elif k == "paste":
            ocr = self.p_source.get().startswith("Pick")
            st.update(click_first=self.p_click.get(),
                      cx=int(fnum(self.cx.get())), cy=int(fnum(self.cy.get())),
                      source="ocr" if ocr else "fixed",
                      text=self.p_textbox.get("1.0", "end-1c"),
                      x=int(fnum(self.x.get())), y=int(fnum(self.y.get())),
                      aw=int(fnum(self.aw.get(), 300)),
                      ah=int(fnum(self.ah.get(), 60)),
                      method={"Windows text": "uia",
                              "OCR (picture)": "ocr"}.get(self.method.get(),
                                                          "auto"),
                      pmode=self.p_mode.get().lower(), pairs=self._pairs(),
                      nomatch={"Skip": "skip", "Stop": "stop"}.get(
                          self.p_nomatch.get(), "default"),
                      default=self.p_default.get(), enter=self.p_enter.get(),
                      how="type" if self.p_how.get() == "Type letters"
                      else "paste")
            if ocr and not st["pairs"]:
                messagebox.showerror("Step", "Add at least one pair",
                                     parent=self)
                return
            if ocr and st["pmode"] == "regex":
                for pr in st["pairs"]:
                    try:
                        re.compile(pr["find"])
                    except re.error as e:
                        messagebox.showerror("Step", f"Regex problem in "
                                             f"\u201c{pr['find']}\u201d: {e}",
                                             parent=self)
                        return
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
        self.tv = ttk.Treeview(fr, columns=("n", "name", "steps", "rep",
                                            "then"),
                               show="headings", height=7,
                               selectmode="browse")
        for c, t, w, a in (("n", "#", 40, "center"),
                           ("name", "Name", 260, "w"),
                           ("steps", "Steps", 80, "center"),
                           ("rep", "Repeat", 100, "center"),
                           ("then", "When finished", 150, "w")):
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
                                      ("▼ Down", lambda: self.move(1)),
                                      ("💾 Export all", self.export_all),
                                      ("📥 Import", self.import_file),
                                      ("📋 Copy all", self.copy_all),
                                      ("📋 Paste", self.paste_all))):
            soft_button(g, t, cmd).grid(row=i // 3, column=i % 3,
                                        sticky="ew", padx=3, pady=3)
        for c in range(3):
            g.columnconfigure(c, weight=1, uniform="b")
        self.info = self.label(self.body, "", size=10, bold=False,
                               fg="#2e7d32")
        self.info.pack(anchor="w", pady=(4, 0))
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
                len(sq["steps"]), "forever" if lp == 0 else f"{lp} times",
                {"next": "→ next", "goto": f"→ {sq.get('then_seq', '?')}"}.get(
                    sq.get("then"), "stop")))
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
            old = self.app.seqs[i]["name"]
            self.app.seqs[i]["name"] = name
            for sq in self.app.seqs:          # keep links to it working
                if sq.get("then_seq") == old:
                    sq["then_seq"] = name
                for st in all_steps(sq["steps"]):
                    for k in ("yes_seq", "no_seq"):
                        if st.get(k) == old:
                            st[k] = name
            self.app.switch_seq(self.app.cur, save=False)
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

    # ---- copy all / export / import
    def _all_data(self):
        self.app._sync_loops()
        return {"keypresser_sequences": 1,
                "seqs": json.loads(json.dumps(self.app.seqs))}

    def _add_seqs(self, data):
        """Add sequences from exported data; returns how many."""
        if isinstance(data, dict):
            data = data.get("seqs", [])
        if not isinstance(data, list):
            raise ValueError("not a KeyPresser sequences file")
        new = [q for q in data if isinstance(q, dict) and "steps" in q]
        if not new:
            raise ValueError("no sequences found")
        rename = {}
        for q in new:
            q.setdefault("name", "Imported")
            q.setdefault("loops", "0")
            nm = self.unique(q["name"])
            rename[q["name"]] = nm
            q["name"] = nm
            self.app.seqs.append(q)
        for q in new:                       # fix links between them
            if q.get("then_seq") in rename:
                q["then_seq"] = rename[q["then_seq"]]
            for st in all_steps(q["steps"]):
                for k in ("yes_seq", "no_seq"):
                    if st.get(k) in rename:
                        st[k] = rename[st[k]]
        self.app._save_settings()
        self.refresh(len(self.app.seqs) - 1)
        return len(new)

    def export_all(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Save all sequences",
            defaultextension=".json", initialfile="my_sequences.json",
            filetypes=[("Sequences", "*.json")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self._all_data(), f, indent=1,
                              ensure_ascii=False)
                self.info.config(text=f"✔ Saved {len(self.app.seqs)} "
                                      f"sequences to {os.path.basename(path)}",
                                 fg="#2e7d32")
            except Exception as e:
                self.info.config(text=f"✖ Could not save: {e}", fg=RED)

    def import_file(self):
        path = filedialog.askopenfilename(
            parent=self, title="Import sequences",
            filetypes=[("Sequences", "*.json"), ("All files", "*.*")])
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    k = self._add_seqs(json.load(f))
                self.info.config(text=f"✔ Imported {k} sequences",
                                 fg="#2e7d32")
            except Exception as e:
                self.info.config(text=f"✖ Could not import: {e}", fg=RED)

    def copy_all(self):
        self.clipboard_clear()
        self.clipboard_append(json.dumps(self._all_data(),
                                         ensure_ascii=False))
        self.info.config(text=f"✔ Copied {len(self.app.seqs)} sequences - "
                              "paste them on another PC or in a message",
                         fg="#2e7d32")

    def paste_all(self):
        try:
            k = self._add_seqs(json.loads(self.clipboard_get()))
            self.info.config(text=f"✔ Pasted {k} sequences", fg="#2e7d32")
        except Exception as e:
            self.info.config(text=f"✖ Clipboard has no sequences ({e})",
                             fg=RED)

    def ok(self):
        i = self.sel()
        self.result = i if i is not None else self.app.cur
        self.destroy()


class ProjectsDialog(Dialog):
    """Each project is its own JSON file in the 'projects' folder."""

    def __init__(self, app):
        super().__init__(app.root, "Projects")
        self.app = app
        app._save_settings()
        self.label(self.body, "Each project is saved as its own file:",
                   bold=False, fg="#555").pack(anchor="w")
        self.label(self.body, PROJECTS_DIR, size=10, bold=False,
                   fg="#1565c0").pack(anchor="w")
        fr = tk.Frame(self.body, bg=self.BG)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv = ttk.Treeview(fr, columns=("name", "seqs", "changed"),
                               show="headings", height=7, selectmode="browse")
        for c, t, w, a in (("name", "Project", 230, "w"),
                           ("seqs", "Sequences", 90, "center"),
                           ("changed", "Last changed", 150, "center")):
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
                                      ("📥 Import file", self.import_file),
                                      ("💾 Export file", self.export_file),
                                      ("📂 Open folder", self.open_folder))):
            soft_button(g, t, cmd, size=11).grid(row=i // 4, column=i % 4,
                                                 sticky="ew", padx=3, pady=3)
        for c in range(4):
            g.columnconfigure(c, weight=1, uniform="b")
        self.info = self.label(self.body, "", size=10, bold=False,
                               fg="#2e7d32")
        self.info.pack(anchor="w", pady=(4, 0))
        self.refresh(app.project)
        self.footer()
        self.foot.winfo_children()[0].config(text="✔  Open")

    def msg(self, text, ok=True):
        self.info.config(text=text, fg="#2e7d32" if ok else RED)

    def sel(self):
        s = self.tv.selection()
        return s[0] if s else None

    def refresh(self, select=None):
        self.tv.delete(*self.tv.get_children())
        for name in list_projects():
            d = read_project(name)
            try:
                t = time.strftime("%d %b %Y %H:%M", time.localtime(
                    os.path.getmtime(project_path(name))))
            except OSError:
                t = ""
            self.tv.insert("", "end", iid=name, values=(
                ("▶ " if name == self.app.project else "") + name,
                len(d.get("seqs", [])), t))
        if select and self.tv.exists(select):
            self.tv.selection_set(select)
            self.tv.see(select)

    def unique(self, name):
        have = {n.lower() for n in list_projects()}
        name = safe_name(name)
        if name.lower() not in have:
            return name
        k = 2
        while f"{name} ({k})".lower() in have:
            k += 1
        return f"{name} ({k})"

    def new(self):
        name = NameDialog(self, "New project",
                          self.unique(f"Project {len(list_projects()) + 1}")
                          ).run()
        if name:
            name = self.unique(name)
            write_project(name, new_project_data())
            self.refresh(name)
            self.msg(f"✔ Made \u201c{name}\u201d - tap Open to use it")

    def rename(self):
        old = self.sel()
        if not old:
            return
        name = NameDialog(self, "Rename project", old).run()
        if not name or safe_name(name) == old:
            return
        name = self.unique(name)
        os.replace(project_path(old), project_path(name))
        if old == self.app.project:
            self.app.project = name
            self.app._save_settings()
            self.app.proj_btn.config(text=f"📁  {name}  ▾")
        self.refresh(name)
        self.msg(f"✔ Renamed to \u201c{name}\u201d")

    def copy(self):
        src = self.sel()
        if not src:
            return
        name = self.unique(src + " copy")
        shutil.copyfile(project_path(src), project_path(name))
        self.refresh(name)
        self.msg(f"✔ Copied to \u201c{name}\u201d")

    def delete(self):
        name = self.sel()
        if not name:
            return
        if name == self.app.project:
            messagebox.showinfo("Delete", "This project is open. Open "
                                "another project first, then delete this one.",
                                parent=self)
            return
        if messagebox.askyesno("Delete", f"Delete project \u201c{name}\u201d?"
                               "\nIts file will be removed.", parent=self):
            os.remove(project_path(name))
            self.refresh(self.app.project)
            self.msg(f"✔ Deleted \u201c{name}\u201d")

    def import_file(self):
        path = filedialog.askopenfilename(
            parent=self, title="Import project",
            filetypes=[("KeyPresser project", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get("seqs"), list):
                raise ValueError("not a KeyPresser project or sequences file")
            name = self.unique(os.path.splitext(os.path.basename(path))[0])
            write_project(name, d)
            self.refresh(name)
            self.msg(f"✔ Imported as \u201c{name}\u201d")
        except Exception as e:
            self.msg(f"✖ Could not import: {e}", ok=False)

    def export_file(self):
        name = self.sel()
        if not name:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export project", defaultextension=".json",
            initialfile=name + ".json",
            filetypes=[("KeyPresser project", "*.json")])
        if path:
            try:
                shutil.copyfile(project_path(name), path)
                self.msg(f"✔ Saved a copy to {os.path.basename(path)}")
            except Exception as e:
                self.msg(f"✖ Could not export: {e}", ok=False)

    def open_folder(self):
        try:
            os.makedirs(PROJECTS_DIR, exist_ok=True)
            os.startfile(PROJECTS_DIR)
        except Exception as e:
            self.msg(f"✖ {e}", ok=False)

    def ok(self):
        self.result = self.sel() or self.app.project
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
    elif t == "find":
        return (f"🎯 Find & click: {find_rule_text(st)} → "
                f"✔ {action_text(st, True)} / ✖ {action_text(st, False)}")
    elif t == "group":
        subs = st.get("steps", [])
        names = ", ".join(q.get("name") or describe(q)[:2].strip()
                          for q in subs[:4])
        d = (f"🗂 Group ({len(subs)} sub-step{'s' if len(subs) != 1 else ''})"
             + (f": {names}{'…' if len(subs) > 4 else ''}" if names else ""))
    elif t == "paste":
        if st.get("source") == "ocr":
            d = (f"📋 Paste by reading ({st.get('x')}, {st.get('y')}): "
                 f"{len(st.get('pairs', []))} pair(s)")
        else:
            txt = st.get("text", "").replace("\n", " ⏎ ")
            d = f"📋 Paste \u201c{txt[:40]}{'…' if len(txt) > 40 else ''}\u201d"
        if st.get("click_first"):
            d += f"  ← click ({st.get('cx')}, {st.get('cy')}) first"
        if st.get("enter"):
            d += "  + Enter"
        return d
    elif t == "read":
        mm = st.get("mmode", "contains")
        rule = (f"{st.get('op', '=')} {fmt(st.get('num', 0))}"
                if mm == "number" else f"\u201c{st.get('pattern', '')}\u201d")

        return (f"🔍 Read ({st['x']}, {st['y']}) {mm} {rule} → "
                f"✔ {action_text(st, True)} / ✖ {action_text(st, False)}")
    else:
        return "⏱ Wait"
    n = int(st.get("times", 1))
    if t in ("click", "key", "group") and n > 1:
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
        self.pause = threading.Event()        # set = paused
        self.paused_total = 0.0
        self.pause_started = 0.0
        self.pause_btns = []
        self.live = {}
        self.mini_compact = False
        self.worker = None
        self.kbc = keyboard.Controller()
        self.msc = mouse.Controller()
        self.sending = False
        self.mini = None
        self.mini_rect = None
        self.logfile = open(args.log, "a", encoding="utf-8") if args.log else None

        s = self._load_settings()
        self.mini_compact = bool(s.get("mini_compact", False))
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
        root.after(200, self._live_tick)
        if args.start:
            root.after(400, self.start)
        if args.open_picker:
            root.after(800, self.pick_point)
        if args.pause_at:
            root.after(int(args.pause_at * 1000), self.toggle_pause)
            root.after(int((args.pause_at + args.pause_for) * 1000),
                       self.toggle_pause)
        if args.draw_box_test:
            def _box_done(box):
                self.log(f"box {' '.join(str(int(v)) for v in box)}"
                         if box else "box none")
                self.root.after(100, self.close)
            root.after(800, lambda: draw_box_on_screen(
                self.root, _box_done, hide=(self.root,)))
        if args.show_keyboard:
            root.after(1500, open_touch_keyboard)
        if args.open_projects:
            root.after(800, self.open_projects)
        if args.quit_soon:
            root.after(int(args.quit_soon * 1000), self.close)
        if args.open_seq_list:
            root.after(800, self.open_seq_list)
        if args.open_step_editor is not None:
            root.after(800, lambda: self.edit_step(args.open_step_editor))

    # ---------------------------------------------------------- settings
    def _load_settings(self):
        s = {}
        self.project = "Test"
        if not self.args.no_settings:
            try:
                with open(SETTINGS_FILE, encoding="utf-8") as f:
                    s = json.load(f)
            except Exception:
                s = {}
            try:
                os.makedirs(PROJECTS_DIR, exist_ok=True)
                names = list_projects()
                want = (self.args.project or s.get("project")
                        or (names[0] if names else "My project"))
                found = next((n for n in names
                              if n.lower() == safe_name(want).lower()), None)
                if found is None:
                    # first project ever: bring in the old settings
                    data = ({k: s[k] for k in PROJECT_KEYS if k in s}
                            if not names else {})
                    write_project(want, data or new_project_data())
                    found = safe_name(want)
                self.project = found
                pdata = read_project(found)
                for k in PROJECT_KEYS:
                    s.pop(k, None)
                s.update({k: v for k, v in pdata.items() if k in PROJECT_KEYS})
            except Exception:
                pass
        return self._take_project(s)

    def _take_project(self, s):
        """Load sequences / points / links from settings dict s."""
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
                "hide": self.hide.get(), "ui_size": self.ui_size,
                "mini_compact": self.mini_compact}

    def _save_settings(self):
        if self.args.no_settings:
            return
        data = self._state()
        app = {k: v for k, v in data.items() if k not in PROJECT_KEYS}
        app["project"] = self.project
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(app, f, indent=1)
        except Exception:
            pass
        try:
            write_project(self.project, data)
        except Exception as e:
            try:
                self.status.set(f"Could not save project: {e}")
            except Exception:
                pass

    # ---------------------------------------------------------- projects
    def _rebuild(self, s, tab=None):
        for w in self.root.winfo_children():
            w.destroy()
        self._style()
        self._build_ui(s)
        self._refresh_all()
        if tab is not None:
            self.nb.select(tab)

    def switch_project(self, name):
        if self.running() or self.args.no_settings:
            return
        self._save_settings()
        pdata = read_project(name) or new_project_data()
        s = self._state()
        for k in PROJECT_KEYS:
            s.pop(k, None)
        s.update({k: v for k, v in pdata.items() if k in PROJECT_KEYS})
        self.project = name
        tab = self.nb.index("current")
        self._take_project(s)
        self._rebuild(s, tab)
        self._save_settings()
        self.status.set(f"Opened project \u201c{name}\u201d")

    def open_projects(self):
        if self.running():
            return
        if self.args.no_settings and not self.args.open_projects:
            self.status.set("Projects are off in test mode")
            return
        r = ProjectsDialog(self).run()
        if r and r != self.project:
            self.switch_project(r)
        elif hasattr(self, "proj_btn"):
            self.proj_btn.config(text=f"📁  {self.project}  ▾")

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
        self.proj_btn = big_button(topbar, f"📁  {self.project}  ▾",
                                   self.open_projects, bg="#37474f",
                                   abg="#455a64", size=12, padx=12, pady=7)
        self.proj_btn.pack(side="left")
        tk.Label(topbar, text="", bg=self.BG, fg="#37474f",
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
        wd = tk.Frame(sq, bg=self.BG)
        wd.pack(fill="x", pady=(6, 0))
        self._lbl(wd, "When finished:  ", bold=True).pack(side="left")
        cur_sq = self.seqs[self.cur]
        self.then_var = tk.StringVar(value={"next": "Next sequence",
                                            "goto": "Go to sequence"}.get(
            cur_sq.get("then"), "Stop"))
        self.then_seq = tk.StringVar(value=cur_sq.get("then_seq", ""))
        Choice(wd, self.then_var, WHEN_DONE, cols=3, size=11
               ).pack(side="left", fill="x", expand=True)
        self.then_row = tk.Frame(sq, bg=self.BG)
        self._lbl(self.then_row, "   then run:  ").pack(side="left")
        seq_chooser(self.then_row, self.then_seq,
                    lambda: [q["name"] for q in self.seqs], self.root
                    ).pack(side="left", fill="x", expand=True)
        self.then_var.trace_add("write", lambda *a: self._then_changed())
        self.then_seq.trace_add("write", lambda *a: self._then_changed())
        self._then_changed(save=False)

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

        sr = tk.Frame(bot, bg=self.BG)
        sr.pack(fill="x", pady=(8, 4))
        self.start_btn = big_button(sr, "", self.toggle, bg=GREEN,
                                    abg=GREEN_A, size=17, pady=14)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.pause_btn = big_button(sr, "⏸  PAUSE", self.toggle_pause,
                                    bg="#ef6c00", abg="#fb8c00", size=15,
                                    pady=14)
        self.pause_btns = [self.pause_btn]
        if self.running():
            self.pause_btn.pack(side="left", padx=(6, 0))
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
        self._rebuild(s, tab)
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

    def _then_changed(self, save=True):
        if getattr(self, "_switching", False) or not hasattr(self,
                                                             "then_row"):
            return
        sq = self.seqs[self.cur]
        sq["then"] = {"Next sequence": "next",
                      "Go to sequence": "goto"}.get(self.then_var.get(),
                                                    "stop")
        sq["then_seq"] = self.then_seq.get()
        if sq["then"] == "goto":
            self.then_row.pack(fill="x", pady=(4, 0))
        else:
            self.then_row.pack_forget()
        if save:
            self._save_settings()

    def switch_seq(self, i, save=True):
        if 0 <= self.cur < len(self.seqs):
            self._sync_loops()
        self.cur = i
        self.steps = self.seqs[i]["steps"]
        if hasattr(self, "loops"):
            self.loops.set(str(self.seqs[i].get("loops", "0")))
        if hasattr(self, "then_var"):
            self._switching = True
            self.then_var.set({"next": "Next sequence",
                               "goto": "Go to sequence"}.get(
                self.seqs[i].get("then"), "Stop"))
            self.then_seq.set(self.seqs[i].get("then_seq", ""))
            self._switching = False
            self._then_changed(save=False)
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
        st = StepDialog(self.root, base,
                        [q["name"] for q in self.seqs]).run()
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
        st = StepDialog(self.root, self.steps[i],
                        [q["name"] for q in self.seqs]).run()
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
        self.gate()
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

    def paste_text(self, text, how="paste"):
        """Put text where the cursor is: clipboard + Ctrl+V, or typed."""
        self.gate()
        if not text:
            return
        self.sending = True
        try:
            if how == "type":
                self.kbc.type(text)
            else:
                set_clipboard_text(text)
                time.sleep(0.05)
                with self.kbc.pressed(Key.ctrl):
                    self.kbc.press("v")
                    self.kbc.release("v")
                time.sleep(0.15)
        finally:
            time.sleep(0.02)
            self.sending = False

    def read_at(self, x, y, aw, ah, method, want=None):
        """Read screen text, hiding the floating window if it's in the
        way. Returns (text, source, error)."""
        r = self.mini_rect
        covered = r and not (x + aw / 2 < r[0] or x - aw / 2 > r[2] or
                             y + ah / 2 < r[1] or y - ah / 2 > r[3])
        if covered:
            self.q.put(("mini_hide", None))
            time.sleep(0.3)
        try:
            return read_screen_text(method, x, y, aw, ah, want=want)
        finally:
            if covered:
                self.q.put(("mini_show", None))

    def press_key(self, name):
        keys = KEYS.get(name, (Key.right,))
        self.gate()
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
        elif key == Key.f9:
            self.q.put(("pause", None))
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
            self._sync_loops()
            cfg = {"seqs": json.loads(json.dumps(self.seqs)),
                   "cur": self.cur, "delay": delay}
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
        self.pause.clear()
        self.paused_total = 0.0
        self.live = {"v0": self.vnow(), "cd": None, "read": None,
                     "step": "", "desc": "",
                     "counts": {"click": 0, "key": 0, "link": 0, "read": 0}}
        self.pause_btn.pack(side="left", padx=(6, 0))
        self._draw_pause_btns()
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()
        self.start_btn.config(text="■  STOP", bg=RED, activebackground=RED_A)
        if self.hide.get():
            self.show_mini()

    # floating mini Stop window --------------------------------------
    def show_mini(self):
        self.root.withdraw()
        BG, PANEL, SUB = "#1f2a30", "#2b3a42", "#9fb3bf"
        m = self.mini = tk.Toplevel(self.root)
        m.overrideredirect(True)
        m.attributes("-topmost", True)
        m.configure(bg=BG)
        W = sz(320)
        wrap = W - sz(24)

        def L(master, text="", size=10, fg="white", bold=False, bg=BG,
              **kw):
            return tk.Label(master, text=text, bg=bg, fg=fg, anchor="w",
                            justify="left", wraplength=wrap,
                            font=(FONT, sz(size), "bold" if bold else
                                  "normal"), **kw)

        # header: drag handle, elapsed time, collapse
        hd = tk.Frame(m, bg=BG)
        hd.pack(fill="x", padx=8, pady=(6, 0))
        handle = L(hd, "⠿  KeyPresser", 10, SUB, True)
        handle.pack(side="left")
        tk.Button(hd, text="▸" if self.mini_compact else "▾",
                  command=self._toggle_mini_detail, bg=BG, fg=SUB, bd=0,
                  activebackground=PANEL, activeforeground="white",
                  font=(FONT, sz(13), "bold"), padx=sz(8), cursor="hand2"
                  ).pack(side="right")
        self.mi_elapsed = L(hd, "⏱ 0:00", 10, SUB)
        self.mi_elapsed.pack(side="right", padx=(0, 6))
        self.mi_toggle = hd.winfo_children()[1]

        self.mini_status = L(m, "Starting...", 10, "white")
        self.mini_status.pack(fill="x", padx=10, pady=(2, 4))

        # details
        d = self.mi_detail = tk.Frame(m, bg=BG)
        self.mi_step = L(d, "", 11, "white", True)
        self.mi_step.pack(fill="x", padx=10)
        self.mi_desc = L(d, "", 10, SUB)
        self.mi_desc.pack(fill="x", padx=10)

        cd = tk.Frame(d, bg=PANEL)
        cd.pack(fill="x", padx=8, pady=(6, 0))
        top = tk.Frame(cd, bg=PANEL)
        top.pack(fill="x", padx=8, pady=(6, 0))
        self.mi_cd_what = L(top, "⏳ —", 10, SUB, bg=PANEL)
        self.mi_cd_what.config(wraplength=wrap - sz(90))
        self.mi_cd_what.pack(side="left")
        self.mi_cd_num = tk.Label(top, text="", bg=PANEL, fg="#ffd54f",
                                  font=(FONT, sz(20), "bold"))
        self.mi_cd_num.pack(side="right")
        self.mi_bar = tk.Canvas(cd, height=sz(7), bg="#37474f",
                                highlightthickness=0, width=W - sz(32))
        self.mi_bar.pack(fill="x", padx=8, pady=(2, 8))

        rd = self.mi_read_box = tk.Frame(d, bg=PANEL)
        rd.pack(fill="x", padx=8, pady=(6, 0))
        rt = tk.Frame(rd, bg=PANEL)
        rt.pack(fill="x", padx=8, pady=(6, 0))
        L(rt, "🔍 Last read", 10, SUB, True, bg=PANEL).pack(side="left")
        self.mi_read_ago = L(rt, "", 9, SUB, bg=PANEL)
        self.mi_read_ago.pack(side="right")
        self.mi_read_text = L(rd, "— nothing read yet —", 11, "#fff59d",
                              bg=PANEL)
        self.mi_read_text.pack(fill="x", padx=8)
        self.mi_read_rule = L(rd, "", 10, SUB, bg=PANEL)
        self.mi_read_rule.pack(fill="x", padx=8)
        self.mi_read_res = L(rd, "", 11, "white", True, bg=PANEL)
        self.mi_read_res.pack(fill="x", padx=8, pady=(0, 6))

        self.mi_counts = L(d, "", 10, SUB)
        self.mi_counts.pack(fill="x", padx=10, pady=(6, 0))
        if not self.mini_compact:
            d.pack(fill="x")

        br = self.mi_buttons = tk.Frame(m, bg=BG)
        br.pack(fill="x", padx=8, pady=8)
        pb = big_button(br, "⏸  PAUSE", self.toggle_pause, bg="#ef6c00",
                        abg="#fb8c00", size=14, padx=10, pady=11)
        pb.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.pause_btns.append(pb)
        big_button(br, "■  STOP", self.stop.set, bg=RED, abg=RED_A,
                   size=14, padx=10, pady=11).pack(side="left", fill="x",
                                                   expand=True)
        self._draw_pause_btns()
        m.update_idletasks()
        m.geometry(f"{W}x{m.winfo_reqheight()}"
                   f"+{self.root.winfo_screenwidth() - W - 16}+16")
        self._refresh_mini()

        def press(e):
            m._dx, m._dy = e.x_root - m.winfo_x(), e.y_root - m.winfo_y()

        def drag(e):
            m.geometry(f"+{e.x_root - m._dx}+{e.y_root - m._dy}")
            self._update_mini_rect()

        for wdg in (handle, hd, self.mini_status, self.mi_step,
                    self.mi_desc, self.mi_elapsed):
            wdg.bind("<ButtonPress-1>", press)
            wdg.bind("<B1-Motion>", drag)
        m.after(100, self._update_mini_rect)

    def _toggle_mini_detail(self):
        if not self.mini:
            return
        self.mini_compact = not self.mini_compact
        if self.mini_compact:
            self.mi_detail.pack_forget()
        else:
            self.mi_detail.pack(fill="x", after=self.mini_status)
        self.mi_toggle.config(text="▸" if self.mini_compact else "▾")
        self._fit_mini()

    def _fit_mini(self):
        m = self.mini
        if not m:
            return
        m.update_idletasks()
        m.geometry(f"{m.winfo_width()}x{m.winfo_reqheight()}"
                   f"+{m.winfo_x()}+{m.winfo_y()}")
        self._update_mini_rect()

    def _refresh_mini(self):
        """Fill the floating window from self.live (called on updates)."""
        if not self.mini:
            return
        lv = self.live
        try:
            self.mi_step.config(text=lv.get("step", ""))
            self.mi_desc.config(text=lv.get("desc", ""))
            c = lv.get("counts", {})
            self.mi_counts.config(
                text=f"🖱 {c.get('click', 0)}   ⌨ {c.get('key', 0)}   "
                     f"🔗 {c.get('link', 0)}   🔍 {c.get('read', 0)}   "
                     f"📋 {c.get('paste', 0)}")
            r = lv.get("read")
            if r:
                src = {"uia": "Windows text", "ocr": "OCR"}.get(r["src"],
                                                                r["src"])
                txt = r["text"] or "(no text found)"
                if len(txt) > 90:
                    txt = txt[:90] + "…"
                self.mi_read_text.config(
                    text=f"\u201c{txt}\u201d" + (f"   [{src}]" if src else ""))
                self.mi_read_rule.config(text=f"Rule: {r['rule']}")
                if r.get("final"):
                    self.mi_read_res.config(
                        text=("✔ match" if r["ok"] else "✖ no match")
                        + f"  →  {r['action']}",
                        fg="#81c784" if r["ok"] else "#e57373")
                else:
                    self.mi_read_res.config(
                        text=("✔ match" if r["ok"] else "✖ not yet")
                        + "  ·  checking…", fg="#ffd54f")
        except tk.TclError:
            pass
        self._fit_mini()

    def _live_tick(self):
        """10x per second: countdown, elapsed time, 'x s ago'."""
        try:
            if self.running() and self.live:
                lv = self.live
                now = self.vnow()
                el = max(0, now - lv.get("v0", now))
                h, rem = divmod(int(el), 3600)
                el_txt = (f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h
                          else f"{rem // 60}:{rem % 60:02d}")
                cd = lv.get("cd")
                paused = self.pause.is_set()
                if cd:
                    end, total, what = cd
                    left = max(0.0, end - now)
                    num = (f"{int(left // 60)}:{int(left % 60):02d}"
                           if left >= 60 else f"{left:.1f}")
                    frac = (left / total) if total > 0 else 0
                else:
                    what, num, frac = "working…", "", 0
                if paused:
                    what = "⏸ paused · " + what
                if self.mini:
                    self.mi_elapsed.config(text=f"⏱ {el_txt}")
                    self.mi_cd_what.config(text=f"⏳ {what}")
                    self.mi_cd_num.config(text=num)
                    bw = self.mi_bar.winfo_width()
                    self.mi_bar.delete("all")
                    if frac > 0:
                        self.mi_bar.create_rectangle(
                            0, 0, int(bw * frac), sz(8),
                            fill="#ffb300" if not paused else "#90a4ae",
                            width=0)
                    r = lv.get("read")
                    if r:
                        ago = max(0, int(now - r["t"]))
                        self.mi_read_ago.config(
                            text="just now" if ago < 2 else f"{ago}s ago")
                else:
                    extra = f"   ⏳ {what} {num}s" if num else ""
                    self.count_var.set(self._counts_text() + extra)
        except tk.TclError:
            pass
        self.root.after(100, self._live_tick)

    def _counts_text(self):
        c = self.live.get("counts", {}) if self.live else {}
        return (f"Clicks: {c.get('click', 0)} · Keys: {c.get('key', 0)} · "
                f"Links: {c.get('link', 0)} · Reads: {c.get('read', 0)}")

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
    def vnow(self):
        """Clock that stands still while paused."""
        now = time.perf_counter()
        p = self.paused_total
        if self.pause.is_set():
            p += now - self.pause_started
        return now - p

    def gate(self):
        """Block here while paused."""
        while self.pause.is_set() and not self.stop.is_set():
            time.sleep(0.05)

    def wait_until(self, t):
        while not self.stop.is_set():
            if self.pause.is_set():
                time.sleep(0.05)
                continue
            left = t - self.vnow()
            if left <= 0:
                return True
            time.sleep(min(left, 0.01))
        return False

    def wait(self, secs, what=None):
        secs = max(0.0, secs)
        if what and secs >= 0.15:
            self.q.put(("cd", (self.vnow() + secs, secs, what)))
            ok = self.wait_until(self.vnow() + secs)
            self.q.put(("cd", None))
            return ok
        return self.wait_until(self.vnow() + secs)

    def toggle_pause(self):
        if not self.running():
            return
        if self.pause.is_set():
            self.paused_total += time.perf_counter() - self.pause_started
            self.pause.clear()
            msg = "▶ Resumed"
        else:
            self.pause_started = time.perf_counter()
            self.pause.set()
            msg = "⏸ Paused - tap Resume to continue"
        self.status.set(msg)
        if self.mini:
            self.mini_status.config(text=msg)
        self._draw_pause_btns()

    def _draw_pause_btns(self):
        paused = self.pause.is_set()
        for b in list(self.pause_btns):
            try:
                b.config(text="▶  RESUME" if paused else "⏸  PAUSE",
                         bg=GREEN if paused else "#ef6c00",
                         activebackground=GREEN_A if paused else "#fb8c00")
            except Exception:
                self.pause_btns.remove(b)

    def countdown(self, n):
        if n > 0:
            self.q.put(("cd", (self.vnow() + n, n, "Starting – switch to "
                                                   "your window")))
        for s in range(n, 0, -1):
            self.q.put(("status", f"Starting in {s}..."))
            if not self.wait(1):
                self.q.put(("cd", None))
                return False
        self.q.put(("cd", None))
        return True

    # sequence worker ----------------------------------------------------
    def work_sequence(self, cfg, test=False):
        """Run a sequence; Read steps or 'When finished' can switch to
        another sequence. Group steps run their own sub-steps."""
        if "seqs" in cfg:
            seqs, cur = cfg["seqs"], cfg["cur"]
        else:
            seqs = [{"name": "Test", "steps": cfg["steps"],
                     "loops": cfg["loops"]}]
            cur = 0
        n = {"click": 0, "key": 0, "link": 0, "read": 0, "paste": 0}
        if not self.countdown(cfg["delay"]):
            self.q.put(("finished", "Stopped"))
            return
        ctx = {"seqs": seqs, "cur": cur, "n": n, "test": test,
               "stop_reason": "", "loop": 0, "total": "", "sname": ""}
        switched = False
        while not self.stop.is_set():
            sq = seqs[ctx["cur"]]
            steps = sq["steps"]
            loops = max(0, int(fnum(sq.get("loops", 0))))
            ctx["sname"] = sq["name"]
            if switched:
                self.log(f"seq 0 0 switch {sq['name']}")
            switched = True
            if not test:
                self.q.put(("seqswitch", ctx["cur"]))
            jump = None                  # sequence index to switch to
            loop = 0
            every = any(st.get("run") != "once" for st in steps)
            while (loops == 0 or loop < loops) and not self.stop.is_set() \
                    and steps and jump is None:
                if loop >= 1 and not every:
                    break      # only "once" steps: nothing left to repeat
                loop += 1
                ctx["loop"] = loop
                ctx["total"] = "∞" if loops == 0 else loops
                sig = self.exec_steps(steps, ctx, "")
                if isinstance(sig, tuple):           # ("seq", index)
                    jump = sig[1]
            if self.stop.is_set():
                break
            if jump is None:
                then = sq.get("then", "stop")
                if then in ("next", "goto"):
                    jump = self._target_seq(seqs, then, sq.get("then_seq"),
                                            ctx["cur"])
                    if jump is None:
                        ctx["stop_reason"] = ("last sequence" if then ==
                                              "next" else "sequence not found")
                        break
                else:
                    break
            if test:
                break
            ctx["cur"] = jump
            self.wait(0.05)
        done = (f"{n['click']} clicks, {n['key']} key presses, "
                f"{n['link']} links, {n['read']} reads")
        if n.get("paste"):
            done += f", {n['paste']} pastes"
        if ctx["stop_reason"] and not test:
            done += f" ({ctx['stop_reason']})"
        self.q.put(("finished", ("Stopped · " if self.stop.is_set()
                                 else "Done · ") + done))

    @staticmethod
    def _target_seq(seqs, kind, name, here):
        """index to switch to, or None (= stop)"""
        if kind == "next":
            return here + 1 if here + 1 < len(seqs) else None
        if kind == "goto":
            for k, sq in enumerate(seqs):
                if sq["name"].lower() == (name or "").lower():
                    return k
        return None

    def call_seq(self, j, ctx):
        """Run sequence j (its own repeat count, forever = once), then come
        back. Returns None to continue, or 'stop' / ('seq', i)."""
        depth = ctx.get("depth", 0)
        if depth >= 10:
            return self._halt(ctx, "too many sequences calling each other")
        saved = {k: ctx[k] for k in ("cur", "sname", "loop", "total")}
        sq = ctx["seqs"][j]
        loops = max(0, int(fnum(sq.get("loops", 1))))
        loops = loops or 1
        ctx.update(cur=j, sname=sq["name"], depth=depth + 1)
        self.log(f"seq 0 0 call {sq['name']}")
        if not ctx["test"]:
            self.q.put(("seqswitch", j))
        sig = None
        for lp in range(1, loops + 1):
            if self.stop.is_set():
                break
            ctx["loop"], ctx["total"] = lp, loops
            sig = self.exec_steps(sq["steps"], ctx, "")
            if sig == "nextloop":
                sig = None
                continue
            if sig:
                break
        ctx.update(saved)
        ctx["depth"] = depth
        if sig or self.stop.is_set():
            return sig or "stop"
        self.log(f"seq 0 0 return {saved['sname']}")
        if not ctx["test"]:
            self.q.put(("seqswitch", saved["cur"]))
        return None

    def _halt(self, ctx, reason):
        ctx["stop_reason"] = reason
        self.stop.set()
        return "stop"

    def exec_steps(self, steps, ctx, prefix):
        """Run a list of steps (the sequence, or a group's sub-steps).
        Returns None (finished), 'nextloop', ('seq', index) or 'stop'."""
        n, loop = ctx["n"], ctx["loop"]
        i = 0
        while i < len(steps) and not self.stop.is_set():
            st = steps[i]
            nxt = i + 1
            sid = f"{prefix}{i + 1}"
            if not ctx["test"] and not prefix:
                self.q.put(("highlight", i))
            if st.get("run") == "once" and loop > 1:
                i = nxt
                continue
            nm = st.get("name") or ""
            label = (f"{ctx['sname']} · loop {loop}/{ctx['total']} · step "
                     f"{sid}" + (f" · {nm}" if nm else ""))
            self.q.put(("status", label))
            self.q.put(("live", {
                "step": f"📂 {ctx['sname']}  ·  Loop {loop}/{ctx['total']}  ·  "
                        f"Step {sid}" + (f"  ·  {nm}" if nm else ""),
                "desc": describe(st)}))
            t = st.get("type")
            times = max(1, int(st.get("times", 1)))
            sig = None
            if t in ("click", "key"):
                for k in range(times):
                    if self.stop.is_set():
                        break
                    if t == "click":
                        self.do_click(st["x"], st["y"],
                                      st.get("button", "Left"), True)
                        n["click"] += 1
                        self.log(f"seq {loop} {sid} click {st['x']} {st['y']}")
                    else:
                        self.press_key(st.get("key"))
                        n["key"] += 1
                        self.log(f"seq {loop} {sid} key {st.get('key')}")
                    self.q.put(("count", n))
                    if k < times - 1:
                        self.wait(random.uniform(st.get("tmin", 0),
                                                 st.get("tmax", 0)),
                                  f"gap before "
                                  f"{'click' if t == 'click' else 'key'}"
                                  f" {k + 2} of {times}")
            elif t == "group":
                for k in range(times):
                    if self.stop.is_set():
                        break
                    self.log(f"seq {loop} {sid} group {k + 1}/{times}")
                    sig = self.exec_steps(st.get("steps", []), ctx, f"{sid}.")
                    if sig:
                        break
                    if k < times - 1:
                        self.wait(random.uniform(st.get("tmin", 0),
                                                 st.get("tmax", 0)),
                                  f"gap before group repeat {k + 2} of "
                                  f"{times}")
            elif t == "link":
                self.gate()
                open_link(st["url"])
                n["link"] += 1
                self.log(f"seq {loop} {sid} link {st['url']}")
                self.q.put(("count", n))
            elif t == "paste":
                out, why, rtext = None, "", ""
                if st.get("source") == "ocr":
                    self.gate()
                    mode = st.get("pmode", "contains")
                    pairs = st.get("pairs", [])
                    rtext, src, err = self.read_at(
                        st.get("x", 0), st.get("y", 0),
                        fnum(st.get("aw", 300)), fnum(st.get("ah", 60)),
                        st.get("method", "auto"),
                        want=lambda tx: any(pair_matches(mode, pr["find"], tx)
                                            for pr in pairs))
                    hit = next((pr for pr in pairs
                                if pair_matches(mode, pr["find"], rtext)),
                               None)
                    n["read"] += 1
                    if hit:
                        out = hit["paste"]
                    elif st.get("nomatch") == "stop":
                        why = "no pair matched → stop"
                    elif st.get("nomatch") == "skip":
                        why = "no pair matched → skip"
                    else:
                        out = st.get("default", "")
                    self.q.put(("read", {
                        "text": rtext, "src": src, "ok": bool(hit),
                        "rule": f"{len(pairs)} pair(s), {mode}",
                        "final": True,
                        "action": (f"paste \u201c"
                                   f"{fill_placeholders(out, rtext)[:30]}"
                                   f"\u201d" if out is not None else why)}))
                else:
                    out = st.get("text", "")
                if out is not None:
                    out = fill_placeholders(out, rtext)
                    if st.get("click_first"):
                        self.do_click(st.get("cx", 0), st.get("cy", 0),
                                      "Left", True)
                        time.sleep(0.15)
                    self.paste_text(out, st.get("how", "paste"))
                    if st.get("enter"):
                        self.press_key("Enter")
                    n["paste"] += 1
                    self.log(f"seq {loop} {sid} paste {out!r}")
                else:
                    self.log(f"seq {loop} {sid} pastenone "
                             f"{st.get('nomatch')}")
                self.q.put(("count", n))
                if out is None and st.get("nomatch") == "stop":
                    return self._halt(ctx, "Paste step: no pair matched")
            elif t == "read":
                ok, text, src = self.do_read(st, label)
                n["read"] += 1
                self.q.put(("count", n))
                self.q.put(("read", {
                    "text": text, "src": src, "ok": ok,
                    "rule": rule_text(st), "final": True,
                    "action": action_text(st, ok)}))
                self.log(f"seq {loop} {sid} read "
                         f"{'match' if ok else 'nomatch'} {text!r}")
                short = (text[:40] + "…") if len(text) > 40 else text
                self.q.put(("status", f"{label} · read \u201c{short}\u201d → "
                                      f"{'✔' if ok else '✖'} "
                                      f"{action_text(st, ok)}"))
                ret, sig, nxt = self._branch(st, ok, ctx, steps, nxt, "Read")
                if ret:
                    return ret
            elif t == "find":
                target, ms, src = self.do_find(st, label)
                ok = target is not None
                n["read"] += 1
                if ok:
                    l_, t_, r_, b_ = target["rect"]
                    cx = int((l_ + r_) / 2) + int(fnum(st.get("dx", 0)))
                    cy = int((t_ + b_) / 2) + int(fnum(st.get("dy", 0)))
                    self.do_click(cx, cy, st.get("button", "Left"), True)
                    n["click"] += 1
                    self.log(f"seq {loop} {sid} find found {cx} {cy} "
                             f"{target['text']!r}")
                else:
                    self.log(f"seq {loop} {sid} find notfound {len(ms)}")
                self.q.put(("count", n))
                self.q.put(("read", {
                    "text": (f"{len(ms)} found · clicked #{ms.index(target) + 1}"
                             f" \u201c{target['text'][:40]}\u201d" if ok else
                             f"not found ({len(ms)} matches)"),
                    "src": src, "ok": ok, "rule": find_rule_text(st),
                    "final": True, "action": action_text(st, ok)}))
                self.q.put(("status", f"{label} · {'✔ clicked' if ok else '✖ not found'}"
                                      f" → {action_text(st, ok)}"))
                ret, sig, nxt = self._branch(st, ok, ctx, steps, nxt, "Find")
                if ret:
                    return ret
            if self.stop.is_set():
                return "stop"
            gap = random.uniform(st.get("amin", 0), st.get("amax", 0))
            if gap > 0:
                self.q.put(("status", f"{label} · waiting {gap:.1f}s"))
                self.wait(gap, "wait before next step")
            if sig:
                return sig
            i = nxt
        return "stop" if self.stop.is_set() else None

    def _branch(self, st, ok, ctx, steps, nxt, who):
        """Apply a Read / Find result. Returns (ret, sig, nxt): if ret is
        set, the step list must return it right away."""
        act = st.get("on_yes" if ok else "on_no", "Continue")
        sel_seq = st.get("yes_seq" if ok else "no_seq")
        if act == "Stop":
            return self._halt(ctx, f"stopped by {who} step"), None, nxt
        if act == "Next loop":
            return None, "nextloop", nxt
        if act == "Go to step":
            tgt = int(st.get("yes_step" if ok else "no_step", 1))
            return None, None, min(max(1, tgt), len(steps)) - 1
        if act in ("Next sequence", "Go to sequence"):
            j = self._target_seq(ctx["seqs"],
                                 "next" if act == "Next sequence" else "goto",
                                 sel_seq, ctx["cur"])
            if j is None:
                return self._halt(ctx, "no next sequence"
                                  if act == "Next sequence"
                                  else "sequence not found"), None, nxt
            return None, ("seq", j), nxt
        if act == "Run sequence & return":
            j = self._target_seq(ctx["seqs"], "goto", sel_seq, ctx["cur"])
            if j is None:
                return self._halt(ctx, "sequence not found"), None, nxt
            sub = self.call_seq(j, ctx)
            if sub:
                return sub, None, nxt
        return None, None, nxt

    def find_now(self, st):
        """find_targets, hiding the floating window while searching."""
        x0, y0, w, h = find_area(st)
        r = self.mini_rect
        covered = r and (st.get("whole", True) or not (
            x0 + w < r[0] or x0 > r[2] or y0 + h < r[1] or y0 > r[3]))
        if covered:
            self.q.put(("mini_hide", None))
            time.sleep(0.3)
        try:
            return find_targets(st)
        finally:
            if covered:
                self.q.put(("mini_show", None))

    def do_find(self, st, label):
        """Search until found or the time limit passes."""
        limit = fnum(st.get("timeout", 0))
        end = self.vnow() + limit
        target, ms, src = None, [], ""
        if limit > 0:
            self.q.put(("cd", (end, limit, f"looking for "
                                           f"\u201c{st.get('keyword', '')}"
                                           f"\u201d")))
        while not self.stop.is_set():
            self.gate()
            target, ms, src, err = self.find_now(st)
            if err and not ms:
                self.q.put(("status", f"{label} · find: {err[:80]}"))
            self.q.put(("read", {
                "text": f"{len(ms)} found", "src": src,
                "ok": target is not None, "rule": find_rule_text(st),
                "final": False, "action": ""}))
            if target is not None or self.vnow() >= end:
                break
            self.wait(min(0.7, max(0.0, end - self.vnow())))
        if limit > 0:
            self.q.put(("cd", None))
        return target, ms, src

    def do_read(self, st, label):
        """Read text for a Read step; keep checking until it matches or
        the time limit passes. Returns (matched, text)."""
        limit = fnum(st.get("timeout", 0))
        end = self.vnow() + limit
        text, src = "", ""
        if limit > 0:
            self.q.put(("cd", (end, limit, "checking text until it "
                                           "matches")))
        while not self.stop.is_set():
            self.gate()
            x, y = st["x"], st["y"]
            aw, ah = fnum(st.get("aw", 300)), fnum(st.get("ah", 60))
            r = self.mini_rect
            covered = r and not (x + aw / 2 < r[0] or x - aw / 2 > r[2] or
                                 y + ah / 2 < r[1] or y - ah / 2 > r[3])
            if covered:
                self.q.put(("mini_hide", None))
                time.sleep(0.3)
            text, src, err = read_screen_text(
                st.get("method", "auto"), x, y, aw, ah,
                want=lambda tx: text_matches(st, tx))
            if covered:
                self.q.put(("mini_show", None))
            if err and not text:
                self.q.put(("status", f"{label} · read error: {err[:80]}"))
            ok = text_matches(st, text)
            self.q.put(("read", {"text": text, "src": src, "ok": ok,
                                 "rule": rule_text(st), "final": False,
                                 "action": ""}))
            if ok or self.vnow() >= end:
                if limit > 0:
                    self.q.put(("cd", None))
                return ok, text, src
            self.q.put(("status", f"{label} · waiting for text..."))
            self.wait(min(0.7, max(0.0, end - self.vnow())))
        self.q.put(("cd", None))
        return False, text, src

    # timers worker -------------------------------------------------------
    def work_timers(self, cfg):
        if not self.countdown(cfg["delay"]):
            self.q.put(("finished", "Stopped"))
            return
        start = self.vnow()
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
            what = {"key": "next key press", "link": "next link",
                    "point": f"next click (point {t.get('i', 0) + 1})"}[t["kind"]]
            left = t["next"] - self.vnow()
            if left > 0.15:
                self.q.put(("cd", (t["next"], left, what)))
            if not self.wait_until(t["next"]):
                break
            self.q.put(("cd", None))
            if t["kind"] == "key":
                self.press_key(cfg["key"])
                n["key"] += 1
                self.log(f"key {n['key']}")
                if cfg["limit"] and n["key"] >= cfg["limit"]:
                    tasks.remove(t)
                else:
                    t["next"] = self.vnow() + random.uniform(
                        cfg["kmin"], cfg["kmax"])
            elif t["kind"] == "link":
                l = t["l"]
                self.gate()
                open_link(l["url"])
                n["link"] += 1
                self.log(f"link {t['i'] + 1} {l['url']}")
                if l["mode"] == "once":
                    tasks.remove(t)
                else:
                    t["next"] = self.vnow() + random.uniform(
                        l["min"], l["max"])
            else:
                p = t["p"]
                self.do_click(p["x"], p["y"], p.get("click", "Left"),
                              cfg["restore"])
                n["click"] += 1
                self.log(f"click {t['i'] + 1} {p['x']} {p['y']}")
                t["next"] = self.vnow() + random.uniform(p["min"],
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
                    if self.live is not None:
                        self.live["counts"] = dict(val)
                    self.count_var.set(self._counts_text())
                    self._refresh_mini()
                elif msg == "seqswitch":
                    if 0 <= val < len(self.seqs) and val != self.cur:
                        self.switch_seq(val, save=False)
                elif msg == "live":
                    self.live.update(val)
                    self._refresh_mini()
                elif msg == "cd":
                    self.live["cd"] = val
                elif msg == "read":
                    val["t"] = self.vnow()
                    self.live["read"] = val
                    self._refresh_mini()
                elif msg == "mini_hide" and self.mini:
                    self.mini.withdraw()
                elif msg == "mini_show" and self.mini:
                    self.mini.deiconify()
                elif msg == "log":
                    if self.logfile:
                        self.logfile.write(f"{time.time():.3f} {val}\n")
                        self.logfile.flush()
                elif msg == "pause":
                    self.toggle_pause()
                elif msg == "finished":
                    self.pause.clear()
                    self.pause_btn.pack_forget()
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
    p.add_argument("--project", default="")
    p.add_argument("--open-projects", action="store_true")
    p.add_argument("--quit-soon", type=float, default=0)
    p.add_argument("--seq", default="", help="sequence name to select")
    p.add_argument("--open-seq-list", action="store_true")
    p.add_argument("--show-keyboard", action="store_true")
    p.add_argument("--draw-box-test", action="store_true")
    p.add_argument("--pause-at", type=float, default=0)
    p.add_argument("--pause-for", type=float, default=0)
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
