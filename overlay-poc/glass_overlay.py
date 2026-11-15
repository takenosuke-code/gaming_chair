"""
glass_overlay.py  --  Liquid-glass screen-watch overlay (Windows 11 / 10 2004+)

A frosted "liquid glass" panel that floats on top of everything: translucent
acrylic blur, rounded corners, a hairline border, and clean typography. It is
click-through (never steals focus) and excluded from screen capture, so it is
visible to your eyes but blank in screenshots / recordings / screen share.

On a hotkey it *watches your screen*: it grabs a region, runs it through a
pluggable OCR step, hands the text to a pluggable "answer" function, and paints
the result in the glass panel.

Run
---
    python glass_overlay.py

The window chrome (acrylic blur + rounded corners + capture-exclusion) is pure
standard library (tkinter + ctypes). The optional screen-reading pipeline uses
extra packages only if you want OCR / a real AI answer -- see README.md. Without
them the UI still runs and the watcher degrades gracefully with a clear message.

Hotkeys (global; work even though the panel is click-through):
    Ctrl+Alt+Space   capture screen now -> OCR -> answer -> show in panel
    Ctrl+Alt+H       toggle the panel on/off
    Ctrl+Alt+L       lock/unlock click-through (unlock to drag the panel)
    Ctrl+Alt+Arrows  nudge the panel 20px
    Ctrl+Alt+Q       quit
"""

import os
import sys
import ctypes
from ctypes import wintypes
import threading
import tkinter as tk
import tkinter.font as tkfont

# ======================================================================
# Config
# ======================================================================
HERE = os.path.dirname(os.path.abspath(__file__))

PANEL = {"x": 60, "y": 80, "w": 520, "h": 320}   # panel position & size
CAPTURE_REGION = None   # None = whole primary screen; or {"x","y","w","h"}

# Acrylic tint: 0xAABBGGRR (alpha, blue, green, red). Lower alpha = clearer glass.
GLASS_TINT = 0x14141E      # dark slate
GLASS_ALPHA = 0xB4         # ~70% -> frosted but readable
ACCENT = "#7FB0FF"         # title / accent color
TEXT_COLOR = "#F2F4F8"
MUTED = "#9AA3B2"
TITLE_FONT = ("Segoe UI Semibold", 13)
BODY_FONT = ("Segoe UI", 12)
CODE_FONT = ("Cascadia Code", 11)

EXCLUDE_FROM_CAPTURE = True   # keep the panel out of screenshots/recordings
PERIODIC_WATCH_MS = 0         # 0 = hotkey-only; e.g. 5000 = auto every 5s

# ======================================================================
# Win32 plumbing (stdlib ctypes only)
# ======================================================================
if sys.platform != "win32":
    sys.exit("This overlay targets Windows 10 2004+ / Windows 11.")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi

user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020     # click-through
WS_EX_TOOLWINDOW = 0x00000080      # no taskbar / alt-tab
WS_EX_NOACTIVATE = 0x08000000      # never take focus
WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11
GA_ROOT = 2

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
WM_HOTKEY = 0x0312
VK_SPACE = 0x20
VK_H, VK_L, VK_Q = 0x48, 0x4C, 0x51
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28

# --- SetWindowCompositionAttribute: the acrylic "liquid glass" blur ---
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(ACCENT_POLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


def enable_acrylic(hwnd):
    """Frosted acrylic blur-behind -- the core of the 'liquid glass' look."""
    try:
        gradient = (GLASS_ALPHA << 24) | GLASS_TINT
        accent = ACCENT_POLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, gradient, 0)
        data = WINCOMPATTRDATA(
            WCA_ACCENT_POLICY, ctypes.pointer(accent), ctypes.sizeof(accent)
        )
        set_wca = user32.SetWindowCompositionAttribute
        set_wca.argtypes = [wintypes.HWND, ctypes.POINTER(WINCOMPATTRDATA)]
        return bool(set_wca(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def round_corners(hwnd, accent_hex=ACCENT):
    """Win11 rounded corners + a hairline accent border via DWM."""
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_BORDER_COLOR = 34
        DWMWCP_ROUND = 2
        pref = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
        r = int(accent_hex[1:3], 16)
        g = int(accent_hex[3:5], 16)
        b = int(accent_hex[5:7], 16)
        colorref = ctypes.c_uint((b << 16) | (g << 8) | r)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_BORDER_COLOR, ctypes.byref(colorref),
            ctypes.sizeof(colorref),
        )
        return True
    except Exception:
        return False


def set_click_through(hwnd, on):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if on:
        ex |= WS_EX_TRANSPARENT
    else:
        ex &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)


def harden_window(hwnd, capture_excluded=True):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    affinity = WDA_EXCLUDEFROMCAPTURE if capture_excluded else WDA_NONE
    return bool(user32.SetWindowDisplayAffinity(hwnd, affinity))


# ======================================================================
# Screen watcher pipeline  (capture -> OCR -> answer)
# ======================================================================
def grab_screen(region=None):
    """Capture the screen (or a region) to a PIL Image.

    Uses Pillow's ImageGrab if available (simplest, cross-DPI). Returns None if
    Pillow isn't installed -- the watcher then shows an install hint instead of
    crashing. See README for `pip install pillow`.
    """
    try:
        from PIL import ImageGrab
    except Exception:
        return None
    if region:
        bbox = (region["x"], region["y"],
                region["x"] + region["w"], region["y"] + region["h"])
        return ImageGrab.grab(bbox=bbox)
    return ImageGrab.grab()


def ocr_image(img):
    """Pluggable OCR. Uses pytesseract if installed, else returns a hint.

    Swap this body for any OCR you like (Windows.Media.Ocr, a cloud OCR, etc).
    """
    if img is None:
        return ("[no capture] install Pillow for screen capture:\n"
                "    pip install pillow")
    try:
        import pytesseract
    except Exception:
        return ("[captured ok, but no OCR] install Tesseract + pytesseract:\n"
                "    pip install pytesseract   (and install the Tesseract exe)")
    try:
        return pytesseract.image_to_string(img).strip()
    except Exception as e:
        return f"[OCR error] {e}"


def answer_question(text):
    """Pluggable AI answer. Takes the captured/OCR'd text, returns a string.

    Default: a stub. Wire up a real model by filling in the TODO below. The API
    key is read from the OVERLAY_API_KEY environment variable -- never hardcode
    a key in this file.
    """
    text = (text or "").strip()
    if not text:
        return "[watcher] nothing readable on screen yet."

    api_key = os.environ.get("OVERLAY_API_KEY")
    if not api_key:
        preview = text if len(text) <= 400 else text[:400] + " ..."
        return ("[stub answer -- no OVERLAY_API_KEY set]\n"
                "Captured text:\n" + preview + "\n\n"
                "Set OVERLAY_API_KEY and fill in answer_question() to get a "
                "real reply.")

    # --- TODO: wire up your model of choice here -----------------------
    # Example shape (uncomment and `pip install anthropic`):
    #
    #   from anthropic import Anthropic
    #   client = Anthropic(api_key=api_key)
    #   msg = client.messages.create(
    #       model="claude-sonnet-5-5",
    #       max_tokens=1024,
    #       messages=[{"role": "user",
    #                  "content": "Answer concisely:\n\n" + text}],
    #   )
    #   return msg.content[0].text
    # -------------------------------------------------------------------
    return ("[OVERLAY_API_KEY is set, but answer_question() still has the TODO "
            "stub. Fill in the model call to get real answers.]")


# ======================================================================
# The glass panel
# ======================================================================
class GlassOverlay:
    def __init__(self):
        self.visible = True
        self.click_through = True
        self.busy = False

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Slightly translucent whole-window alpha layered on top of the acrylic
        # blur -- keeps text crisp while the background stays frosted.
        self.root.attributes("-alpha", 0.96)
        self.root.geometry(
            f"{PANEL['w']}x{PANEL['h']}+{PANEL['x']}+{PANEL['y']}"
        )
        self.root.configure(bg="#0B0E14")

        # --- content layout ---------------------------------------------
        pad = tk.Frame(self.root, bg="#0B0E14")
        pad.pack(fill="both", expand=True, padx=16, pady=14)

        self.title = tk.Label(
            pad, text="glass watcher", anchor="w", justify="left",
            bg="#0B0E14", fg=ACCENT, font=TITLE_FONT,
        )
        self.title.pack(fill="x")

        self.status = tk.Label(
            pad, text="Ctrl+Alt+Space to read screen", anchor="w",
            bg="#0B0E14", fg=MUTED, font=(BODY_FONT[0], 9),
        )
        self.status.pack(fill="x", pady=(0, 8))

        self.body = tk.Message(
            pad, text="Panel is live. It's blank in any screen capture.\n"
                      "Press Ctrl+Alt+Space to grab what's on screen.",
            anchor="nw", justify="left", bg="#0B0E14", fg=TEXT_COLOR,
            font=BODY_FONT, width=PANEL["w"] - 40,
        )
        self.body.pack(fill="both", expand=True)

        # grab the real top-level HWND, then apply glass + stealth styles
        self.root.update_idletasks()
        self.hwnd = user32.GetAncestor(self.root.winfo_id(), GA_ROOT)

        harden_window(self.hwnd, capture_excluded=EXCLUDE_FROM_CAPTURE)
        got_glass = enable_acrylic(self.hwnd)
        round_corners(self.hwnd)
        if not got_glass:
            self.status.config(
                text="acrylic blur unavailable on this build - plain panel")

        self._start_hotkey_thread()
        if PERIODIC_WATCH_MS:
            self.root.after(PERIODIC_WATCH_MS, self._periodic)

    # --- watcher ------------------------------------------------------
    def watch_now(self):
        if self.busy:
            return
        self.busy = True
        self.status.config(text="reading screen...")
        # run the capture/OCR/answer pipeline off the UI thread
        threading.Thread(target=self._watch_worker, daemon=True).start()

    def _watch_worker(self):
        try:
            # hide self briefly so we don't OCR our own panel (it's already
            # capture-excluded, but ImageGrab on some setups still sees it)
            self.root.after(0, self.root.withdraw)
            img = grab_screen(CAPTURE_REGION)
            self.root.after(0, self.root.deiconify)
            text = ocr_image(img)
            answer = answer_question(text)
        except Exception as e:
            answer = f"[watcher error] {e}"
        self.root.after(0, lambda: self._show_answer(answer))

    def _show_answer(self, answer):
        self.body.config(text=answer)
        self.status.config(text="done - Ctrl+Alt+Space to read again")
        self.busy = False

    def _periodic(self):
        self.watch_now()
        self.root.after(PERIODIC_WATCH_MS, self._periodic)

    # --- window controls ----------------------------------------------
    def toggle(self):
        self.visible = not self.visible
        (self.root.deiconify if self.visible else self.root.withdraw)()

    def toggle_click_through(self):
        self.click_through = not self.click_through
        set_click_through(self.hwnd, self.click_through)
        self.status.config(
            text=("click-through ON" if self.click_through
                  else "click-through OFF - drag to move"))

    def nudge(self, dx, dy):
        self.root.update_idletasks()
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def quit(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    # --- global hotkeys -----------------------------------------------
    def _start_hotkey_thread(self):
        actions = {
            1: self.watch_now,
            2: self.toggle,
            3: self.toggle_click_through,
            4: lambda: self.nudge(-20, 0),
            5: lambda: self.nudge(0, -20),
            6: lambda: self.nudge(20, 0),
            7: lambda: self.nudge(0, 20),
            8: self.quit,
        }

        def run():
            mod = MOD_CONTROL | MOD_ALT
            binds = [
                (1, VK_SPACE), (2, VK_H), (3, VK_L),
                (4, VK_LEFT), (5, VK_UP), (6, VK_RIGHT), (7, VK_DOWN),
                (8, VK_Q),
            ]
            for hid, vk in binds:
                user32.RegisterHotKey(None, hid, mod, vk)
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    act = actions.get(msg.wParam)
                    if act:
                        self.root.after(0, act)
                    if msg.wParam == 8:
                        break
        threading.Thread(target=run, daemon=True).start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    GlassOverlay().run()
