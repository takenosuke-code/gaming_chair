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
