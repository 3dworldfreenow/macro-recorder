#!/usr/bin/env python3
"""
KeyPresser - presses one keyboard key again and again
(default: Right Arrow = "next") with a random gap between presses.

F8 = start / stop     ESC = stop
The key goes to whichever window is active, so click on that window first
(or use the start delay to switch to it).

Needs: pip install pynput
"""

import argparse
import queue
import random
import threading
import time
import tkinter as tk
from tkinter import ttk

from pynput import keyboard
from pynput.keyboard import Key

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


class App:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.kbc = keyboard.Controller()
        self.sending = False
        self.logfile = open(args.log, "a", encoding="utf-8") if args.log else None

        root.title("KeyPresser")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        f = ttk.Frame(root, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Key to press:").grid(row=0, column=0, sticky="w")
        self.key = tk.StringVar(value=args.key if args.key in KEYS
                                else "Right Arrow (next)")
        ttk.Combobox(f, textvariable=self.key, values=list(KEYS),
                     state="readonly", width=20
                     ).grid(row=0, column=1, columnspan=3, sticky="w", pady=3)

        ttk.Label(f, text="Random gap (sec):").grid(row=1, column=0, sticky="w")
        self.gmin = tk.StringVar(value=str(args.min))
        self.gmax = tk.StringVar(value=str(args.max))
        ttk.Spinbox(f, from_=0, to=600, increment=0.5, width=6,
                    textvariable=self.gmin).grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="to").grid(row=1, column=2, padx=4)
        ttk.Spinbox(f, from_=0, to=600, increment=0.5, width=6,
                    textvariable=self.gmax).grid(row=1, column=3, sticky="w",
                                                 pady=3)

        ttk.Label(f, text="Stop after (0 = never):").grid(row=2, column=0,
                                                         sticky="w")
        self.limit = tk.StringVar(value=str(args.limit))
        ttk.Spinbox(f, from_=0, to=999999, increment=1, width=8,
                    textvariable=self.limit).grid(row=2, column=1,
                                                  columnspan=2, sticky="w",
                                                  pady=3)
        ttk.Label(f, text="presses").grid(row=2, column=3, sticky="w")

        ttk.Label(f, text="Start delay (sec):").grid(row=3, column=0,
                                                     sticky="w")
        self.delay = tk.StringVar(value=str(args.delay))
        ttk.Spinbox(f, from_=0, to=60, increment=1, width=6,
                    textvariable=self.delay).grid(row=3, column=1, sticky="w",
                                                  pady=3)

        self.btn = ttk.Button(f, text="▶ Start (F8)", command=self.toggle)
        self.btn.grid(row=4, column=0, columnspan=4, sticky="ew",
                      pady=(10, 4), ipady=4)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self.status, foreground="#0a5"
                  ).grid(row=5, column=0, columnspan=4)
        self.count_var = tk.StringVar(value="Presses: 0")
        ttk.Label(f, textvariable=self.count_var,
                  font=("Segoe UI", 12, "bold")
                  ).grid(row=6, column=0, columnspan=4, pady=2)
        ttk.Label(f, text="F8 start/stop · ESC stop · key goes to the "
                  "active window", foreground="#777"
                  ).grid(row=7, column=0, columnspan=4, pady=(4, 0))

        self.listener = keyboard.Listener(on_press=self._on_key)
        self.listener.daemon = True
        self.listener.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)
        if args.start:
            root.after(300, self.start)

    # ---- hotkeys (ignore the keys we send ourselves)
    def _on_key(self, key):
        if key == Key.f8:
            self.q.put(("toggle", None))
        elif key == Key.esc and not self.sending:
            self.q.put(("stop", None))

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
            a, b = float(self.gmin.get()), float(self.gmax.get())
            limit = max(0, int(float(self.limit.get())))
            delay = max(0, int(float(self.delay.get())))
        except ValueError:
            self.status.set("Check the numbers")
            return
        a, b = max(0.0, min(a, b)), max(0.0, max(a, b))
        key = KEYS.get(self.key.get(), Key.right)
        self.stop.clear()
        self.worker = threading.Thread(target=self.work,
                                       args=(key, a, b, limit, delay),
                                       daemon=True)
        self.worker.start()
        self.btn.config(text="■ Stop (F8 / ESC)")

    def wait(self, secs):
        end = time.perf_counter() + secs
        while not self.stop.is_set() and time.perf_counter() < end:
            time.sleep(0.01)
        return not self.stop.is_set()

    def work(self, key, a, b, limit, delay):
        for s in range(delay, 0, -1):
            self.q.put(("status", f"Starting in {s}... click your window"))
            if not self.wait(1):
                break
        n = 0
        while not self.stop.is_set():
            self.sending = True
            try:
                self.kbc.press(key)
                time.sleep(0.03)
                self.kbc.release(key)
            finally:
                time.sleep(0.02)
                self.sending = False
            n += 1
            self.q.put(("count", n))
            if limit and n >= limit:
                self.q.put(("status", f"Done - {n} presses"))
                break
            gap = random.uniform(a, b)
            self.q.put(("status", f"Pressed #{n} · next in {gap:.2f}s"))
            if not self.wait(gap):
                break
        if self.stop.is_set():
            self.q.put(("status", f"Stopped after {n} presses"))
        self.q.put(("finished", None))

    def poll(self):
        try:
            while True:
                msg, val = self.q.get_nowait()
                if msg == "toggle":
                    self.toggle()
                elif msg == "stop":
                    self.stop.set()
                elif msg == "status":
                    self.status.set(val)
                elif msg == "count":
                    self.count_var.set(f"Presses: {val}")
                    if self.logfile:
                        self.logfile.write(f"{time.time():.3f} press {val}\n")
                        self.logfile.flush()
                elif msg == "finished":
                    self.btn.config(text="▶ Start (F8)")
                    if self.args.quit_when_done:
                        self.close()
                        return
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def close(self):
        self.stop.set()
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
    p.add_argument("--key", default="Right Arrow (next)")
    p.add_argument("--min", type=float, default=0)
    p.add_argument("--max", type=float, default=2)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--delay", type=int, default=3)
    p.add_argument("--start", action="store_true")
    p.add_argument("--quit-when-done", action="store_true")
    p.add_argument("--log", default="")
    args, _ = p.parse_known_args()
    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
