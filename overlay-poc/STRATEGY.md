# Overlay vs Detector — strategy

The whole problem is decided by **what the friend's detector can see**. A
browser is heavily sandboxed; the detector's capability tier changes everything.

## The central fact

A Chrome tab (and a Chrome extension) runs inside the browser sandbox. It
cannot enumerate OS processes, list other windows, read other apps' memory, or
screenshot the desktop. The *only* browser-native signal that crosses the
sandbox is `getDisplayMedia` (screen share) — and that captures an overlay only
if (a) the user is screen-sharing and (b) grants "entire screen", and even then
the capture-exclusion trick below blanks the overlay out. A webcam watches the
person, not the screen.

## Detector tiers

| Tier | What the detector is | What it can see | What beats it | Kernel needed? |
|---|---|---|---|---|
| **1** | Pure JS in a tab | focus/blur, visibilitychange, pointer leave, `window.screen`, devicePixelRatio. Nothing outside the tab. | Any always-on-top, click-through overlay. Don't steal focus. | No — massive overkill |
| **2** | Browser extension | + `chrome.windows`/`tabs` focus, idle state, display geometry. Still sandboxed from the OS. | Same overlay; just never take window focus. | No |
| **3** | Native helper on the same machine | desktop screenshots, `EnumWindows`, process list, (rarely) its own kernel driver. The real opponent. | Capture-exclusion + quiet window; see below. | Only vs a *kernel-level* detector |

## Recommended approach

Build the **userland capture-excluded overlay** (the POC):

- `WS_EX_LAYERED | WS_EX_TRANSPARENT` → transparent + click-through; it never
  steals mouse or keyboard focus, so it emits none of the Tier-1/2 signals.
- `WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE` → no taskbar/alt-tab entry, never
  activates.
- `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` → the DWM compositor
  omits the window from every capture path (PrintScreen, BitBlt, DXGI
  Desktop Duplication, `getDisplayMedia`). Visible to the eye, blank in capture.

This beats Tier 1 and Tier 2 outright, and defeats the two things a Tier-3
detector usually relies on (screenshots and a casual window scan) — with **no
kernel driver, no driver-signing, no bluescreen risk.**

## Where it still loses (and what each assumption is)

- **Window enumeration.** A Tier-3 detector that walks `EnumWindows` /
  `EnumChildWindows` will still find a visible top-level window, toolwindow or
  not. Mitigations (all userland): message-only window + layered child,
  randomized/again-innocuous class and title, or render into another process's
  surface. None make it truly invisible to a determined enumerator.
- **Process list.** The overlay is a process. A detector scanning for unknown
  processes sees `python.exe` (or whatever you ship). Rename/sign/host-inside
  another process to blend in; still not invisible.
- **`WDA_EXCLUDEFROMCAPTURE` is itself a tell.** A native detector can query
  `GetWindowDisplayAffinity` on windows it finds and flag any set to exclude —
  that flag is *unusual*. If the detector does this, the trick that beats its
  screenshots becomes the thing that flags you on enumeration. Tradeoff to
  weigh against the friend's actual approach.
- **Kernel-level detector.** If the friend ships a signed kernel driver (like
  commercial anti-cheat), it can see everything userland hides. Only then does
  a kernel-level overlay even start to make sense — and it's the risky,
  driver-signing, bluescreen-prone path we've been avoiding.

## What the POC assumes

It is built assuming **Tier 3, Windows, detecting via screen capture /
screenshots** — the hardest *common* case, and the one where this trick shines.

- If the detector is **Tier 1 or Tier 2**, you've already won with far less; the
  capture-exclusion is just insurance.
- If the detector is **Tier 3 doing deep window/process enumeration** (not
  screenshots), the capture trick doesn't help and may flag you — you'd pivot to
  the hiding mitigations above, or accept that's a different game.
- If the detector is **kernel-level**, nothing userland wins; that's the only
  scenario where the original "kernel-level" idea is warranted.

**Confirm the friend's detector tier and method before investing further.**
