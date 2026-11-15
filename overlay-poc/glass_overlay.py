"""
glass_overlay.py  --  Apple-grade glass screen-watch overlay (Windows 11 / 10 2004+)

A translucent black-glass panel that floats above everything: frosted acrylic
blur, rounded corners, a hairline border, and razor-sharp monochrome typography.
It is click-through (never steals focus) and excluded from screen capture, so it
is visible to your eyes but blank in screenshots / recordings / screen share.

Design goals (this redesign):
    * See-through   -- a genuine translucent black/dark-grey glass, not a
                       muddy opaque slab. You can read the screen underneath.
    * Razor-sharp   -- the process is per-monitor DPI-aware, so text renders at
                       native resolution instead of being bitmap-stretched (the
                       old "low-res / blurry" look). No fuzz on high-DPI displays.
    * Apple-quality -- restrained monochrome palette, generous spacing, a tidy
                       header, a quiet status line, and clean corners.

On a hotkey it *watches your screen*: it grabs a region, runs it through a
pluggable OCR step, hands the text to a pluggable "answer" function, and paints
the result in the glass panel.

Run
---
    python glass_overlay.py

The window chrome (acrylic glass + rounded corners + capture-exclusion + DPI
awareness) is pure standard library (tkinter + ctypes). The optional
screen-reading pipeline uses extra packages only if you want OCR / a real AI
answer -- see README.md. Without them the UI still runs and the watcher degrades
gracefully with a clear message.

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

# ======================================================================
# Config  --  the look
# ======================================================================
HERE = os.path.dirname(os.path.abspath(__file__))

PANEL = {"x": 64, "y": 84, "w": 500, "h": 300}   # logical px (DPI-scaled at runtime)
CAPTURE_REGION = None   # None = whole primary screen; or {"x","y","w","h"}

# --- Glass (how see-through the frosted panel is) ---------------------
# Acrylic tint is black; a LOW frost alpha keeps it genuinely see-through.
GLASS_TINT = 0x000000      # 0x00BBGGRR -> pure black tint
GLASS_FROST = 0x4D         # ~30% frost: translucent black glass, not a slab
WINDOW_ALPHA = 0.86        # whole-window opacity: more see-through, text stays crisp

# --- Palette (black / dark grey, monochrome -- Apple-like) ------------
TEXT_COLOR = "#F5F5F7"     # off-white, primary text
MUTED = "#98989D"          # secondary / status
FAINT = "#636366"          # hints / footer
DIVIDER = "#2A2A2C"        # hairline rule
BORDER_HEX = "#48484A"     # window border (dark grey)
BASE_BG = "#000000"        # widget backing (sits under WINDOW_ALPHA)

# --- Typography (Segoe UI == closest to SF on Windows) ----------------
TITLE_FONT = ("Segoe UI Semibold", 13)
STATUS_FONT = ("Segoe UI", 9)
BODY_FONT = ("Segoe UI", 12)
CODE_FONT = ("Cascadia Code", 11)
HINT_FONT = ("Segoe UI", 9)

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

# --- SetWindowCompositionAttribute: the acrylic "glass" blur ---
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19


def enable_dpi_awareness():
    """Become per-monitor DPI-aware BEFORE any window exists.

    This is the single biggest fix for the "blurry / low-res" look: a
    DPI-unaware process is rendered at 96 DPI and then bitmap-stretched by the
    compositor on a high-DPI display, which softens every edge. Once aware,
    tkinter draws at the monitor's native resolution and text is pin-sharp.

    Tries Per-Monitor-v2 first, then older fallbacks so it still runs on
    Windows 8.1 / early 10.
    """
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi():
    """Primary-display DPI (96 == 100%). Used to scale geometry + fonts."""
    try:
        return int(user32.GetDpiForSystem())
    except Exception:
        return 96


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
    """Frosted black-glass blur-behind -- the core see-through 'glass' look.

    The acrylic blurs only what is *behind* the window, never the window's own
    text, so this stays fully compatible with razor-sharp typography.
    """
    try:
        gradient = (GLASS_FROST << 24) | GLASS_TINT
        accent = ACCENT_POLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, gradient, 0)
        data = WINCOMPATTRDATA(
            WCA_ACCENT_POLICY, ctypes.pointer(accent), ctypes.sizeof(accent)
        )
        set_wca = user32.SetWindowCompositionAttribute
        set_wca.argtypes = [wintypes.HWND, ctypes.POINTER(WINCOMPATTRDATA)]
        return bool(set_wca(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def round_corners(hwnd, border_hex=BORDER_HEX):
    """Win11 rounded corners + a hairline dark-grey border via DWM."""
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_BORDER_COLOR = 34
        DWMWCP_ROUND = 2
        pref = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
        r = int(border_hex[1:3], 16)
        g = int(border_hex[3:5], 16)
        b = int(border_hex[5:7], 16)
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
        # Whole-window alpha layered on top of the acrylic blur: this is what
        # makes the panel see-through. Text stays crisp because transparency is
        # not blur -- the DPI fix below is what keeps edges sharp.
        self.root.attributes("-alpha", WINDOW_ALPHA)

        # DPI scale: lay the panel out in logical px, then scale to physical px
        # so it's the right size AND pin-sharp on high-DPI displays.
        self.dpi = system_dpi()
        self.scale = self.dpi / 96.0
        # tk 'scaling' is pixels-per-point; set it from real DPI so point-based
        # fonts render at their true physical size (sharp, not stretched).
        try:
            self.root.tk.call("tk", "scaling", self.dpi / 72.0)
        except Exception:
            pass

        w = int(PANEL["w"] * self.scale)
        h = int(PANEL["h"] * self.scale)
        self.root.geometry(f"{w}x{h}+{PANEL['x']}+{PANEL['y']}")
        self.root.configure(bg=BASE_BG)

        px = int(22 * self.scale)   # Apple-ish generous side padding
        py = int(18 * self.scale)

        # --- outer padding frame ---------------------------------------
        pad = tk.Frame(self.root, bg=BASE_BG)
        pad.pack(fill="both", expand=True, padx=px, pady=py)

        # --- header: title (left)  +  status (right) -------------------
        header = tk.Frame(pad, bg=BASE_BG)
        header.pack(fill="x")

        self.title = tk.Label(
            header, text="Assistant", anchor="w",
            bg=BASE_BG, fg=TEXT_COLOR, font=TITLE_FONT,
        )
        self.title.pack(side="left")

        self.status = tk.Label(
            header, text="Ready", anchor="e",
            bg=BASE_BG, fg=MUTED, font=STATUS_FONT,
        )
        self.status.pack(side="right")

        # --- hairline divider ------------------------------------------
        divider = tk.Frame(pad, bg=DIVIDER, height=1)
        divider.pack(fill="x", pady=(int(10 * self.scale), int(12 * self.scale)))

        # --- body: read-only text, comfortable line spacing ------------
        self.body = tk.Text(
            pad, bg=BASE_BG, fg=TEXT_COLOR, font=BODY_FONT,
            relief="flat", highlightthickness=0, borderwidth=0,
            wrap="word", cursor="arrow",
            padx=0, pady=0,
            spacing1=2, spacing3=int(5 * self.scale),
            insertwidth=0,
        )
        self.body.pack(fill="both", expand=True)
        self._set_body(
            "Panel is live, and blank in any screen capture.\n"
            "Press  Ctrl + Alt + Space  to read what's on screen."
        )

        # --- footer: quiet hotkey hints --------------------------------
        self.footer = tk.Label(
            pad,
            text="⌃⌥ Space  read     ⌃⌥ H  hide     "
                 "⌃⌥ L  move     ⌃⌥ Q  quit",
            anchor="w", bg=BASE_BG, fg=FAINT, font=HINT_FONT,
        )
        self.footer.pack(fill="x", pady=(int(10 * self.scale), 0))

        # grab the real top-level HWND, then apply glass + stealth styles
        self.root.update_idletasks()
        self.hwnd = user32.GetAncestor(self.root.winfo_id(), GA_ROOT)

        harden_window(self.hwnd, capture_excluded=EXCLUDE_FROM_CAPTURE)
        got_glass = enable_acrylic(self.hwnd)
        round_corners(self.hwnd)
        if not got_glass:
            self.status.config(text="plain")  # acrylic unsupported on this build

        self._start_hotkey_thread()
        if PERIODIC_WATCH_MS:
            self.root.after(PERIODIC_WATCH_MS, self._periodic)

    # --- body helper (keep it read-only but updatable) ----------------
    def _set_body(self, text):
        self.body.config(state="normal")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", text)
        self.body.config(state="disabled")

    # --- watcher ------------------------------------------------------
    def watch_now(self):
        if self.busy:
            return
        self.busy = True
        self.status.config(text="Reading…")
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
        self._set_body(answer)
        self.status.config(text="Done")
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
            text=("Ready" if self.click_through else "Unlocked · drag"))

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
    enable_dpi_awareness()   # must run before the first window is created
    GlassOverlay().run()
