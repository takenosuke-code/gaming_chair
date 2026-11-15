"""
overlay.py  --  Stealth overlay POC (Windows 10 2004+ / Windows 11)

What it does
------------
Draws a transparent, always-on-top, click-through window that paints text in a
screen region you choose. The window is:

  * click-through  (WS_EX_TRANSPARENT)  -> never steals mouse/keyboard focus
  * no taskbar / no alt-tab entry       (WS_EX_TOOLWINDOW)
  * excluded from screen capture         (SetWindowDisplayAffinity +
                                          WDA_EXCLUDEFROMCAPTURE) -> it is
                                          VISIBLE TO YOUR EYES but BLANK in any
                                          screenshot, screen-recording, OBS, or
                                          browser getDisplayMedia share.

Why this matters for the challenge
----------------------------------
A browser tab (Tier 1: pure JS) and a browser extension (Tier 2) are sandboxed
and cannot see other OS windows at all, so they lose to this outright. A native
detector (Tier 3) is the only thing that *could* see it -- and the two ways a
native detector usually "sees" an overlay are (a) screenshotting the desktop
and (b) enumerating top-level windows. WDA_EXCLUDEFROMCAPTURE kills (a); the
WS_EX_TOOLWINDOW + unremarkable process name makes (b) less obvious. This POC
is the strongest *userland* answer -- no kernel driver, no driver-signing, no
bluescreen risk. See STRATEGY.md for where it still falls short vs a determined
Tier-3 detector.

How to run
----------
    python overlay.py

Uses only the Python standard library (tkinter + ctypes). No pip installs.

Live content: edit overlay_content.txt next to this file -- the overlay
re-reads it ~2x/second, so you can push answers to it from any other process.

Hotkeys (global, work even though the window is click-through):
    Ctrl+Alt+H   toggle the overlay on/off
    Ctrl+Alt+Q   quit
"""

import os
import sys
import ctypes
from ctypes import wintypes
import threading
import tkinter as tk

# ---- config -------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT_FILE = os.path.join(HERE, "overlay_content.txt")

REGION = {"x": 40, "y": 60, "w": 520, "h": 360}   # where the overlay sits
TRANSPARENT_KEY = "#010101"   # this exact bg color becomes fully see-through
TEXT_COLOR = "#39FF14"        # bright green; change to taste
FONT = ("Consolas", 14)
REFRESH_MS = 500              # how often to re-read the content file
# -------------------------------------------------------------------------

if sys.platform != "win32":
    sys.exit("This POC targets Windows 10 2004+ / Windows 11.")

user32 = ctypes.windll.user32
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020     # click-through
WS_EX_TOOLWINDOW = 0x00000080      # no taskbar / alt-tab
WS_EX_NOACTIVATE = 0x08000000      # never take focus
WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11       # invisible to screenshots/recording/share
GA_ROOT = 2

MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
WM_HOTKEY = 0x0312
VK_H = 0x48
VK_Q = 0x51


def harden_window(hwnd, capture_excluded=True):
    """Apply the stealth extended styles + capture exclusion to a real HWND."""
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    affinity = WDA_EXCLUDEFROMCAPTURE if capture_excluded else WDA_NONE
    ok = user32.SetWindowDisplayAffinity(hwnd, affinity)
    return bool(ok)


class Overlay:
    def __init__(self):
        self.visible = True
        self.root = tk.Tk()
        self.root.overrideredirect(True)          # no title bar / border
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.geometry(
            f"{REGION['w']}x{REGION['h']}+{REGION['x']}+{REGION['y']}"
        )
        self.label = tk.Label(
            self.root, text="", justify="left", anchor="nw",
            bg=TRANSPARENT_KEY, fg=TEXT_COLOR, font=FONT,
            wraplength=REGION["w"] - 10,
        )
        self.label.pack(fill="both", expand=True)

        # must exist on screen before we can grab the real top-level HWND
        self.root.update_idletasks()
        self.hwnd = user32.GetAncestor(self.root.winfo_id(), GA_ROOT)
        captured_ok = harden_window(self.hwnd, capture_excluded=True)
        if not captured_ok:
            # Older Windows: fall back to no capture-exclusion (still
            # click-through + toolwindow). Overlay will show in screenshots.
            self.label.config(
                text="[warn] capture-exclusion unavailable on this Windows "
                     "build; overlay will appear in screenshots."
            )

        self._start_hotkey_thread()
        self._tick()

    def _tick(self):
        if self.visible:
            try:
                with open(CONTENT_FILE, "r", encoding="utf-8") as fh:
                    self.label.config(text=fh.read())
            except FileNotFoundError:
                self.label.config(
                    text="(create overlay_content.txt beside overlay.py)"
                )
        self.root.after(REFRESH_MS, self._tick)

    def toggle(self):
        self.visible = not self.visible
        if self.visible:
            self.root.deiconify()
        else:
            self.root.withdraw()

    def quit(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _start_hotkey_thread(self):
        # Global hotkeys run on their own thread with a GetMessage pump,
        # then marshal the action back onto the tk event loop.
        def run():
            if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, VK_H):
                return
            user32.RegisterHotKey(None, 2, MOD_CONTROL | MOD_ALT, VK_Q)
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    if msg.wParam == 1:
                        self.root.after(0, self.toggle)
                    elif msg.wParam == 2:
                        self.root.after(0, self.quit)
                        break
        t = threading.Thread(target=run, daemon=True)
        t.start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not os.path.exists(CONTENT_FILE):
        with open(CONTENT_FILE, "w", encoding="utf-8") as fh:
            fh.write("overlay POC\nedit this file; it refreshes live\n"
                     "Ctrl+Alt+H toggle   Ctrl+Alt+Q quit\n")
    Overlay().run()
