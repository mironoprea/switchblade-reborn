# RESEARCH.md — Protocol dossier (read before coding)

Everything below was gathered 2026-07-08. Facts are tagged:
**[CONFIRMED]** = multiple sources / official. **[SEED]** = from a working
implementation for a *sibling* device (Razer Blade laptop) — probably right for the
DeathStalker Ultimate but must be verified on real hardware. **[UNKNOWN]** = must be
discovered by capture in Phase 1.

## Device identity

- **[CONFIRMED]** Razer DeathStalker Ultimate, model RZ03-00790. USB VID `0x1532`,
  PID `0x0114`. Composite device — Windows hardware IDs seen in the wild include
  `USB\VID_1532&PID_0114&MI_01`, so it exposes multiple interfaces (`MI_00`,
  `MI_01`, …).
- **[CONFIRMED]** Trackpad screen: 4.05", 800×480, 16-bit RGB565 color.
- **[CONFIRMED]** 10 dynamic keys, each with its own small LCD image. Official SDK
  guide says 115×115 px key images; one community source says 116×116.
  Treat exact size as **[UNKNOWN]** until measured from a capture.
- **[SEED]** On the Razer Blade (PID `0x0116`) the Switchblade lives on
  **interface 2**, with bulk **OUT endpoint 0x01** (display data) and
  **endpoint 0x02** for button/input events. On the DeathStalker the interface
  number may differ (the `MI_01` sighting above hints it could be interface 1 or 2)
  — enumerate, don't assume.

## Seed blit protocol (from FxChiP/rzswitchblade, GPL-2.0)

Source: https://github.com/FxChiP/rzswitchblade — Linux libusb library that blits
images to Switchblade devices, explicitly including the DeathStalker Ultimate in its
README. Files: `src/rzsblit_proto.c`, `src/rzsblit_sync.c`, `src/rzscore.c`,
`src/rzswitchblade.h`. **Read these files in full before writing protocol.py** —
fetch them raw from GitHub.

- **[SEED]** Blit packet = 12-byte header + pixel payload, sent as a bulk OUT
  transfer to the touchpad endpoint (0x01 on the Blade).
- **[SEED]** Header layout, six big-endian (`htons`) uint16 fields:

  | offset | field | value |
  |---|---|---|
  | 0 | opcode | `0x0001` (BLIT) |
  | 2 | x1 | rect left |
  | 4 | y1 | rect top |
  | 6 | x2 | rect right |
  | 8 | y2 | rect bottom |
  | 10 | checksum | XOR of the five fields above |

- **[SEED]** Payload = RGB565 pixels for the rect. Pixel byte order (big vs little
  endian per pixel) is not obvious from the summary — if colors look wrong/swapped
  on first success, byte-swap the pixel words.
- **[UNKNOWN]** Whether the rect is inclusive or exclusive of x2/y2, and whether the
  XOR checksum is over the uint16 values or raw bytes. Read the C source; verify on
  hardware.
- **[UNKNOWN]** How dynamic keys are addressed. rzswitchblade's public API only does
  the touchpad (`rzswitchblade_blit_tp_sync`). Two hypotheses to test in Phase 1:
  (a) keys are an extended coordinate region of the same virtual framebuffer
  (blit with y or x beyond 800×480), or (b) a different opcode / different wIndex /
  different endpoint. A USB capture of Synapse setting key images resolves this in
  minutes.
- **[UNKNOWN]** Init / mode-switch sequence: how the trackpad flips from
  mouse mode to display mode, brightness control, and what Synapse sends on device
  attach. Capture scenarios cover these.
- **[UNKNOWN]** Dynamic-key press events: expected on the vendor interface's IN
  endpoint (0x02 on the Blade) but AIDA64's native implementation never got key
  input working — events might instead arrive as HID input reports on interface
  0/1. Test both.

## Prior art (use for reference, do not depend on at runtime)

- **AIDA64 ≥ v8.00** — closed source, but proves 64-bit direct libusb drive of this
  exact LCD on Windows without the Razer SDK. Their v7.99-and-earlier path used
  `RzSwitchbladeSDK2.dll` (32-bit, needs Synapse framework) and was unstable.
  Thread: https://forums.aida64.com/topic/18395-fixed-razer-switchblade-lcd-with-aida64-v799-razer-deathstalker-ultimate/
- **FxChiP/rzswitchblade** — the seed protocol, see above.
- **Official SwitchBlade SDK guide (PDF)** — capability reference (key layout,
  image sizes, gesture semantics):
  https://assets.razerzone.com/eeimages/sbui/Razer_SwitchBladeSDK_Guide.pdf
- **SDK wrappers** (only useful as capture harnesses — they drive the device
  through Razer's DLL so you can record what the DLL sends over USB):
  - https://github.com/SharpBlade/SharpBlade (C#)
  - https://github.com/YourGamesBeOver/RZSB (C#)
  - https://github.com/heroicefforts/gswitchblade (Groovy/JNA)
- **openrazer/openrazer issue #127** — DeathStalker Ultimate support request,
  never completed; confirms pcaps were the missing ingredient.
- **Reverse-engineering blog on SBUI apps** (app/file formats, background reading):
  http://revengrazer.blogspot.com/2013/06/switchblade-ui-apps.html

## Licensing note

rzswitchblade is GPL-2.0. **Do not copy its code** into this project unless the user
accepts GPL for the whole app. Reading it to understand a wire protocol and writing
your own Python implementation is fine (protocol facts are not copyrightable), but
keep the implementation clean-room-ish: derive constants from your own captures
where possible and cite the repo in comments only as documentation.
