# Stealth overlay POC (Windows)

A transparent, always-on-top, **click-through** overlay that paints text in a
screen region — and is **excluded from screen capture**, so it's visible to
your eyes but blank in screenshots, screen recording, OBS, and browser
`getDisplayMedia` screen shares.

## Run

```
python overlay.py
```

Standard library only (tkinter + ctypes). No installs. Needs **Windows 10
version 2004+ or Windows 11** for capture-exclusion; it degrades gracefully on
older builds (still click-through, but will show in screenshots).

- Live content: edit `overlay_content.txt` — the overlay re-reads it ~2x/sec.
- `Ctrl+Alt+H` toggle, `Ctrl+Alt+Q` quit.

## Why it works (short version)

The browser can't see other OS windows, so a tab (Tier 1) or an extension
(Tier 2) can't see this at all. A native detector (Tier 3) is the only thing
that could — and its two usual eyes are:

1. **Screenshotting the desktop** → defeated by `SetWindowDisplayAffinity(hwnd,
   WDA_EXCLUDEFROMCAPTURE)`. The compositor itself leaves the window out of any
   capture, so even a native screenshot comes back blank where the overlay is.
2. **Enumerating top-level windows** → made quieter by `WS_EX_TOOLWINDOW`
   (no taskbar / alt-tab) + an unremarkable process name. Not invisible to a
   determined `EnumWindows` scan — see STRATEGY.md.

This is the strongest **userland** approach: no kernel driver, no driver
signing, no bluescreen risk. See `STRATEGY.md` for where it still loses to a
determined Tier-3 detector and what each approach assumes.

## Verify capture-exclusion

With the overlay running, take a screenshot (`Win+Shift+S` / Snipping Tool) or
start a screen recording. The overlay region should be blank in the capture
while still visible on your monitor. If you have Pillow:

```
python -c "from PIL import ImageGrab; ImageGrab.grab().save('shot.png')"
```

`shot.png` will not contain the overlay text.

---

## Liquid-glass screen watcher (`glass_overlay.py`)

A polished version of the overlay: a frosted **"liquid glass"** panel
(translucent acrylic blur, rounded corners, hairline accent border, clean
Segoe UI typography) that can also **watch your screen** and show an answer.

```
python glass_overlay.py
```

**Window chrome is still standard-library only** (tkinter + ctypes). The glass
look comes from Win32 directly:

- **Acrylic blur** — `SetWindowCompositionAttribute` with
  `ACCENT_ENABLE_ACRYLICBLURBEHIND` (frosted blur-behind).
- **Rounded corners + border** — DWM `DWMWA_WINDOW_CORNER_PREFERENCE` and
  `DWMWA_BORDER_COLOR` (Windows 11).
- Still **click-through**, **always-on-top**, **no taskbar/alt-tab**, and
  **excluded from screen capture** (`WDA_EXCLUDEFROMCAPTURE`) — blank in any
  screenshot / recording / share, same as `overlay.py`.

### Hotkeys (global)

| Key | Action |
|---|---|
| `Ctrl+Alt+Space` | capture screen → OCR → answer → show in panel |
| `Ctrl+Alt+H` | toggle the panel on/off |
| `Ctrl+Alt+L` | lock/unlock click-through (unlock to drag the panel) |
| `Ctrl+Alt+← ↑ → ↓` | nudge the panel 20px |
| `Ctrl+Alt+Q` | quit |

### The screen-watch pipeline (pluggable)

`capture → OCR → answer`, each a plain function you can swap:

1. **`grab_screen(region)`** — screen capture. Uses Pillow's `ImageGrab`.
2. **`ocr_image(img)`** — text extraction. Uses `pytesseract` if present.
3. **`answer_question(text)`** — returns the string to display. **Stubbed by
   default**; fill in the clearly-marked `TODO` to call a model.

If a step's dependency is missing, the panel shows a short install hint instead
of crashing — the UI itself never needs these.

### Optional dependencies (only for the watcher)

```
pip install pillow        # screen capture (grab_screen)
pip install pytesseract   # OCR  — also install the Tesseract engine exe
pip install anthropic     # only if you wire answer_question() to a model
```

### API key (never hardcoded)

`answer_question()` reads the key from the **`OVERLAY_API_KEY`** environment
variable and leaves the actual model call as a `TODO`. No key is stored in the
source. Until you set it and fill the TODO, the panel echoes the captured text
as a stub so you can see the pipeline working end-to-end.

```powershell
$env:OVERLAY_API_KEY = "your-key-here"   # PowerShell, current session only
```
