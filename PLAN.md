# Switchblade Reborn — Strategy Plan

Standalone Windows control app for the Razer DeathStalker Ultimate "Switchblade UI"
(4" 800×480 touch LCD trackpad + 10 LCD dynamic keys), replacing the discontinued
Razer Synapse 2.0. No Razer login, no cloud, no Synapse process required.

This file is the strategy. The implementer works from `BUILD_SPEC.md` and must read
`RESEARCH.md` first. Do not start coding from this file.

---

## 1. Goal

1. Display arbitrary images on the 800×480 trackpad screen without Synapse.
2. Display per-key images on the 10 dynamic keys.
3. React to dynamic-key presses with user-configured actions (launch app, macro, media key).
4. Profiles: named sets of key images + actions, switchable at runtime.
5. Improvements over Synapse (post-MVP): live widgets on the screen (clock, CPU/GPU
   stats, now-playing), automatic profile switch by foreground app, runs at startup,
   zero login.

## 2. Why this is feasible (evidence, see RESEARCH.md for links)

- The device is a USB composite device, VID `0x1532`, PID `0x0114`. The Switchblade
  displays live on a vendor-specific interface separate from the normal HID keyboard
  interfaces.
- AIDA64 v8.00+ drives this exact LCD **via direct libusb, bypassing Razer's SDK
  entirely**. Proof that a Synapse-free native path works on Windows.
- The open-source `rzswitchblade` project (GPL-2.0, Linux) documents the blit
  protocol: bulk OUT endpoint, 12-byte header (`op=0x0001`, rect coords, XOR
  checksum), RGB565 pixel payload. This is our seed protocol.
- The official SwitchBlade SDK PDF documents capabilities/semantics (key count,
  115×115 key images, gestures) even though we won't ship the SDK path.

## 3. Approach decision

Three candidate paths were considered:

- **Path A — wrap RzSwitchbladeSDK2.dll (Razer's SDK).** Rejected as the main path:
  32-bit only, requires Synapse 2.0 framework installed, exactly the dependency we
  are escaping. Kept ONLY as a capture harness: SDK sample apps generate USB traffic
  we can record.
- **Path B — native USB protocol via WinUSB/libusb.** CHOSEN. Proven by AIDA64 and
  rzswitchblade. No Razer software at runtime.
- **Path C — OpenRazer port.** Rejected: Linux-only kernel driver, user runs Windows.

Stack (fixed, do not re-decide): **Python 3.11+, pyusb + libusb-1.0, Pillow, hidapi,
Flask for the local web UI.** Chosen for implementer simplicity and fast iteration;
performance is adequate (full 800×480 RGB565 frame = 750 KB ≈ 30+ fps over USB 2.0
high speed, and we diff-blit anyway).

## 4. Phases and gates

Each phase ends with a **verify sweep** (checklist in BUILD_SPEC). A failed gate
STOPS the project at that phase — do not build on top of an unverified layer.

- **Phase 0 — Recon & safety.** Enumerate the real device (interfaces, endpoints),
  set up capture tooling, document the driver rollback path. Gate: device map
  written; rollback tested.
- **Phase 1 — Proof of life (hard gate).** Bind WinUSB to the Switchblade interface
  only; blit a test image to the trackpad screen using the seed protocol. If the
  seed protocol fails, fall back to USB captures of Synapse/SDK traffic and correct
  it. Then solve dynamic-key images and key-press events (captures likely needed).
  Gate: image on screen, image on a key, keypress printed to console. **Nothing else
  gets built until this passes.**
- **Phase 2 — Core daemon (MVP).** Device manager with reconnect, renderer with
  dirty-rect diffing, input dispatcher, JSON profiles, actions. CLI control. This is
  the MVP: config-file-driven, no GUI.
- **Phase 3 — Control web UI.** Local Flask app: edit profiles, assign images/actions,
  live preview, profile switching.
- **Phase 4 — Better-than-Synapse.** Screen widgets (clock, system stats,
  now-playing), foreground-app profile auto-switch, autostart, optional keyboard
  backlight control via standard Razer HID feature reports (no driver swap needed
  for that interface).

## 5. Key risks

| Risk | Mitigation |
|---|---|
| Seed protocol (from Razer Blade) differs on DeathStalker (different PID, maybe different interface #) | Phase 0 enumerates the actual device; Phase 1 has a capture fallback; nothing is hardcoded from the Blade without verification |
| Dynamic-key image addressing is undocumented (rzswitchblade only covers the trackpad) | Dedicated capture scenario in Phase 1; keys may be an extended region of the same framebuffer or a second op-code — both hypotheses listed in BUILD_SPEC |
| Wrong interface rebound with Zadig → keyboard dead | Hard safety rule: only the vendor-specific interface is ever touched; rollback procedure written and tested in Phase 0 BEFORE any rebinding |
| Trackpad mode switching (mouse mode vs screen mode) needs an init sequence | Capture on device replug + Synapse start; treated as a first-class discovery item |
| Synapse fights the app over the device | Runtime rule: app refuses to start its device loop if Synapse processes are running |
| AIDA64-style: LCD works but key events don't arrive on the vendor interface | Fallback: listen for key events on the HID interfaces via hidapi (no rebinding needed) |

## 6. Out of scope

- Linux/macOS support.
- Touch gestures on the trackpad beyond basic tap coordinates (stretch goal only).
- Running Synapse-era "SBUI apps" (YouTube/Twitter applets). We replace, not emulate.
- Macro recording UI in MVP (macros are hand-written JSON until Phase 3).
