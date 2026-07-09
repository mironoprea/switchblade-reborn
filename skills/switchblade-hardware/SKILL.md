---
name: switchblade-hardware
description: Continue Switchblade Reborn hardware bring-up for the Razer DeathStalker Ultimate SwitchBlade UI. Use when working in this repo on SDK/USB display backends, physical LCD key rendering, HID key input, USBPcap captures, Motorola ADB visual verification, driver binding, or unresolved direct USB protocol gaps.
---

# Switchblade Hardware

## Workflow

1. Read [references/handoff.md](references/handoff.md) first. It contains the current hardware state, verified commands, and remaining traps.
2. Prefer `--backend auto` or `--backend sdk` when the Razer SDK is installed and MI_03 is on the original Razer driver. This is the verified path for rendering the touchpad and all ten physical LCD keys.
3. Use `--backend usb` only when MI_03 is bound to WinUSB. That direct path renders the main touch LCD, but direct physical-key image addressing is still unknown.
4. Verify hardware-visible changes with the Motorola camera through `tools/adb_photo.py`; inspect the pulled image before declaring success.
5. Run `pytest` before handoff. Current expected baseline is 148 passing tests.

## Guardrails

- Do not bind WinUSB to HID interfaces 0, 1, or 2.
- Do not delete the USBPcap driver package just because an `oem*.inf` number looks familiar; `oem1.inf` may be USBPcap on this machine.
- Treat the old key image rectangle at `y=480` as rejected for direct USB. It writes onto the main touch LCD, not the physical keys.
- Keep capture artifacts out of commits unless the user asks; `captures/phone/*.jpg` is useful for visual proof but normally ignored.
