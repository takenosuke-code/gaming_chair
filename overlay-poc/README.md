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

A polished version of the overlay: a translucent **black-glass** panel
(DPI-aware for razor-sharp text, acrylic blur-behind, rounded corners, hairline
border, clean monochrome Segoe UI typography) that can also **watch your
screen** and describe what's on it — a quick way to confirm the capture → model
pipeline is hooked up.

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
| `Ctrl+Alt+Space` | capture screen → describe via model → show in panel |
| `Ctrl+Alt+H` | toggle the panel on/off |
| `Ctrl+Alt+L` | lock/unlock click-through (unlock to drag the panel) |
| `Ctrl+Alt+← ↑ → ↓` | nudge the panel 20px |
| `Ctrl+Alt+Q` | quit |

### The screen-watch pipeline

`capture → describe`, two plain functions you can swap:

1. **`grab_screen(region)`** — screen capture. Uses Pillow's `ImageGrab`.
2. **`describe_screen(img)`** — sends the screenshot to an Azure AI Foundry
   vision deployment and returns its description. Uses stdlib `urllib`, so there
   is nothing extra to `pip install` for the model call itself.

This is a **connectivity check**: the model simply reports what it sees on
screen, so you can confirm capture → model is working. The system prompt is a
clearly-labeled `DESCRIBE_SYSTEM_PROMPT` constant near the top of the file —
tweak it freely. If capture or config is missing, the panel shows a short hint
instead of crashing.

### Dependency (only for the describer)

```
pip install pillow        # screen capture (grab_screen)
```

The Azure call uses the Python standard library only — no SDK needed.

### Connect Azure AI Foundry (keys never hardcoded)

`describe_screen()` reads everything from environment variables; **no secret is
stored in the source**.

1. In the [Azure AI Foundry portal](https://ai.azure.com) (or the Azure OpenAI
   resource in the Azure portal), create a resource and **deploy a
   vision-capable model** (e.g. `gpt-4o` / `gpt-4o-mini`). Give the deployment a
   name.
2. From the resource's **Keys and Endpoint** page, copy the **endpoint**
   (looks like `https://<your-resource>.openai.azure.com`) and a **key**.
3. Set the env vars (PowerShell, current session only):

```powershell
$env:AZURE_AI_ENDPOINT   = "https://<your-resource>.openai.azure.com"
$env:AZURE_AI_DEPLOYMENT = "<your-vision-deployment-name>"
$env:AZURE_AI_KEY        = "<your-key>"
# optional, defaults to a recent version:
# $env:AZURE_AI_API_VERSION = "2024-10-21"
```

4. Run `python glass_overlay.py`, press **Ctrl+Alt+Space**, and the panel should
   describe your screen. If it doesn't, the panel prints the Azure error (check
   the endpoint, deployment name, key, and `api-version`).
