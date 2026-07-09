# HANDOFF — Switchblade Reborn Build & Keyboard Connection Attempt

**Date:** 2026-07-09
**Repo:** https://github.com/mironoprea/switchblade-reborn
**Branch:** master (build-fixes merged via PR #2; code-review hardening merged via PR #3 — see §8)
**Hardware:** Razer DeathStalker Ultimate (VID 0x1532 / PID 0x0114)
**OS:** Windows 11, Python 3.13.5

---

## 1. What Was Done

### 1.1 Clone and Build
- Cloned the repo from GitHub into switchblade-reborn/.
- Created a Python venv: python -m venv venv.
- Installed all dependencies from requirements.txt: pyusb 1.3.1, libusb-package 1.0.30.0, Pillow 12.3.0, hidapi 0.15.0, flask 3.1.3, psutil 7.2.2, pywin32 312, numpy 2.5.1.
- Installed pytest 9.1.1.
- Ran the full test suite: 104/104 tests pass.
- Validated profiles/profiles.json: valid.

### 1.2 Patches Applied (3 files)

These patches are required for the app to work on Windows. They are committed on the build-fixes branch.

#### Patch 1: app/usb_link.py — libusb backend injection
Problem: On Windows, pyusb cannot auto-discover the libusb-1.0 DLL. The libusb-package pip package ships the DLL but requires explicit backend registration.
Fix: Added a module-level import of libusb_package and created a _BACKEND global, then passed backend=_BACKEND to usb.core.find().

Code added near top of module:

    try:
        import libusb_package
        _BACKEND = libusb_package.get_libusb1_backend()
    except Exception:
        _BACKEND = None

And in _try_connect():

    self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid, backend=_BACKEND)

#### Patch 2: tools/enumerate.py — same libusb backend fix
Applied the same _BACKEND pattern to the diagnostic script so python tools/enumerate.py works.

#### Patch 3: app/daemon.py — INITIALIZING to READY transition
Problem: The daemon main loop never called link.mark_ready(), so the device would get stuck in the INITIALIZING state and never reach READY, meaning no rendering ever happened. The mark_ready() method existed but was only called from CLI commands (blit-screen, blit-key), not from the daemon loop.
Fix: Added a transition in the main loop:

    if state == INITIALIZING:
        self.link.mark_ready()

Also added INITIALIZING to the imports from .usb_link.

---

## 2. Device Topology (Confirmed on Real Hardware)

The Razer DeathStalker Ultimate presents as a USB composite device with these interfaces:

| Interface | Class   | Subclass | Protocol | Endpoints                              | Purpose               |
|-----------|---------|----------|----------|----------------------------------------|-----------------------|
| 0         | 0x03    | 0x01     | 0x02     | Interrupt IN 0x81 (8 bytes)            | Standard keyboard     |
| 0 (alt)   | 0x00    | 0x00     | 0x00     | Interrupt IN 0x81 (64 bytes)           | Alternate setting     |
| 1         | 0x03    | 0x00     | 0x01     | Interrupt IN 0x82 (16 bytes)           | HID media/consumer    |
| 2         | 0x03    | 0x01     | 0x01     | Interrupt IN 0x83 (8 bytes)            | HID system control    |
| 3         | 0xFF    | 0xF0     | 0x00     | Bulk OUT 0x01 (512), Bulk OUT 0x02 (512), no bulk IN observed | Switchblade UI |

Key finding: Interface 3 is the vendor-specific interface. Live enumeration on
2026-07-09 reports two bulk OUT endpoints, 0x01 and 0x02, with no vendor bulk IN
endpoint. UsbLink now prefers 0x01 for blits when multiple OUT endpoints are
present and treats missing vendor IN as no vendor-input path.

Instance ID: USB\VID_1532&PID_0114&MI_03\6&3b17fa3&0&0003

---

## 3. What Does NOT Work

### 3.1 The Blocking Issue: WinUSB Driver Not Bound to Interface 3

The daemon starts, finds the device, identifies interface 3 (class 0xFF), and attempts to claim it. But usb.util.claim_interface() fails with:

    Cannot claim interface 3: Operation not supported or unimplemented on this platform

This means the vendor interface (MI_03) does NOT have the WinUSB driver bound to it. Instead, it has the Razer vendor driver (oem16.inf, original name rzhnet.inf, provider Razer Inc).

pyusb/libusb can only access USB interfaces that are bound to the WinUSB (or libusbK) driver. The Razer driver claims the interface exclusively and does not expose it to libusb.

### 3.2 What This Means
- The app code is correct: device discovery, interface scanning, endpoint identification, and safety guards all work.
- The protocol layer, renderer, profile validation, web UI, and all 116 tests pass.
- The only thing preventing the keyboard from working is the driver binding on interface 3.

---

## 4. What Was Tried to Fix the Driver

### Attempt 1: pnputil /add-driver winusb.inf /instanceid ...

    pnputil /add-driver C:\Windows\INF\winusb.inf /instanceid USB\VID_1532&PID_0114&MI_03\6&3b17fa3&0&0003

Result: Added driver packages: 1, but the device still shows oem16.inf as its active driver. Windows considers the Razer driver a better match than generic WinUSB, so it does not switch.

### Attempt 2: pnputil /add-driver ... /install

    pnputil /add-driver C:\Windows\INF\winusb.inf /instanceid ... /install

Result: Added driver packages: 0. The /install flag did not help because WinUSB generic INF does not have a hardware ID match for this device.

### Attempt 3: Custom INF file (switchblade-winusb.inf)
Created a custom INF that explicitly matches USB\VID_1532&PID_0114&MI_03 and includes winusb.inf. Tried pnputil /add-driver switchblade-winusb.inf /install /instanceid ... — Access is denied (needs admin elevation). Tried Start-Process -Verb RunAs (elevated) — the command ran but the device still keeps the Razer driver.

Root cause: Even with the custom INF installed in the driver store, Windows ranks the Razer driver (rzhnet.inf) as a better match than the custom WinUSB INF. To force the switch, you need to either:
1. Remove/uninstall the Razer driver from this specific interface (not the HID ones), then let Windows pick WinUSB, OR
2. Use Zadig (GUI tool) which calls the WinUSB installer API directly and forces the binding, OR
3. Use pnputil /delete-driver oem16.inf /uninstall to remove the Razer driver for this interface, then let Windows pick WinUSB.

### What Still Needs to Be Done (Driver Binding)
The recommended path from the repo own README is Zadig:
1. Download Zadig from https://zadig.akeo.ie/
2. Options then List All Devices
3. Find Razer DeathStalker Ultimate (Interface 3) — the vendor-specific one (class 0xFF)
4. Set driver to WinUSB, click Replace Driver
5. Only touch interface 3 — never touch interfaces 0, 1, 2 (HID keyboard/mouse)

Rollback if needed: Device Manager then Universal Serial Bus devices then Razer DeathStalker Ultimate (Interface 3) then Uninstall device (check delete driver) then unplug/replug keyboard then Windows restores the Razer driver automatically.

---

## 5. Potential Issues Beyond the Driver

These have NOT been tested on hardware yet (blocked by the driver issue):

### 5.1 Init Sequence [RESOLVED — PORTED from FxChiP/rzswitchblade]
FxChiP/rzswitchblade source was mined (Section H.1 of IMPLEMENTATION_PLAN). The C library opens the device, detaches the kernel driver (Linux), claims the interface, and immediately blits — no init/mode-switch packet is sent. A `Daemon._initialize_device()` no-op hook has been added so that if hardware testing with WinUSB reveals an init sequence is needed, there is a place to add it. PROTOCOL.md updated to [PORTED].

### 5.2 Key Image Addressing [UNKNOWN]
The code assumes keys are laid out at y=480 (below the screen) in a virtual framebuffer, each 115x115 pixels. PROTOCOL.md says this is a hypothesis — a different opcode or addressing scheme may be needed. Needs a USB capture of Synapse assigning key images.

### 5.3 Key Event Format [UNKNOWN]
Live enumeration reports no vendor bulk IN endpoint on interface 3, so key events
likely arrive on one of the HID interrupt IN endpoints. parse_key_event() still
implements two legacy raw-byte hypotheses (1-indexed byte + flag, or bitmask),
but the actual format needs a capture of pressing the LCD keys while Synapse runs.

### 5.4 Pixel Endian
RGB565 byte order defaults to big-endian. If colors appear swapped on hardware, switch to little-endian via the endian parameter.

### 5.5 No Profile Images
profiles/images/ has placeholder PNGs (bg.png, key0.png to key9.png) but they may be dummy/test images. Real images will be needed for a usable setup.

---

## 6. How to Run (Once Driver is Fixed)

    cd switchblade-reborn
    .\venv\Scripts\activate
    python -m app.cli run

Web UI at http://127.0.0.1:8377.

Diagnostic tools:

    python tools\enumerate.py          # Show all interfaces/endpoints
    python tools\blit_test.py <image>   # Send a test image to the screen
    python tools\listen_keys.py         # Listen for key press events

---

## 7. Summary for the Advisor

**Last updated:** 2026-07-09 (post PR #3 code-review hardening — see §8; this
section describes the PR #2 milestone and remains accurate for the hardware state).

Working:
- Repo builds, all dependencies install, tests pass (116 total after HID diagnostic hardening).
- Device is detected, vendor interface (3) correctly identified with bulk OUT endpoints 0x01/0x02.
- App code patched to work on Windows (libusb backend, INITIALIZING to READY transition).
- Profile validation, web UI, renderer, protocol layer all functional.

IMPLEMENTATION_PLAN Sections A-E, H.1 completed (PR #2 merged to master):
- Deleted malformed switchblade-winusb.inf (broken HKR,,DriverFl line).
- Fixed PROTOCOL.md device map to confirmed 4-interface topology [CONFIRMED].
- Ported FxChiP/rzswitchblade findings: header format [PORTED], no init sequence
  needed [PORTED], key size may be 116x116 [PORTED], separate header/payload
  transfers noted as diagnostic fallback.
- Added Daemon._initialize_device() no-op hook (C.3).
- Fixed bulk IN read length 64 -> 512 in input_listener.py and listen_keys.py (C.4).
- Added threading.Lock to UsbLink.write() and read() for thread-safety (C.5).

Blocked on hardware (Sections F, G, H.2/H.3, I):
- Interface 3 has the Razer driver (rzhnet.inf / oem16.inf), not WinUSB. pyusb cannot
  claim it. Need Zadig (Section F) to bind WinUSB to interface 3 only.
- After Zadig: hardware bring-up (Section G) — blit test, key events, full daemon run.
- Key image addressing still [UNKNOWN] — FxChiP only does touchpad blitting.
- Key event format still [UNKNOWN] — likely on HID interfaces because no vendor bulk IN endpoint is exposed.
- Brightness control still [UNKNOWN] — not present in FxChiP source.
- USB captures (Section H.2) may still be needed for key addressing + key events, but
  must be done BEFORE Zadig binding (while Razer driver is still active).

---

## 8. PR #3 — Code Review Hardening (2026-07-09)

A full-codebase review (Fable 5 agent, findings verified against the code before
applying) landed as PR #3 on top of the PR #2 build fixes. It fixes real bugs
that would have made hardware bring-up fail silently, plus quality cleanup. **None
of this changes the remaining hardware plan (Zadig → bring-up → captures); it just
means the code you run after Zadig is now correct where it previously wasn't.**

**Test baseline after PR #3 was 110 tests: 108 pass + 2 `pyusb`-gated skips** (the
2 skips run and pass on CI, which now installs `requirements.txt`). Current local
baseline after HID diagnostic hardening is 116 passing tests.

### Highest-impact fixes (these directly affect bring-up)
- **USB read timeouts were treated as fatal disconnects** (`usb_link.py`). The old
  check `"timeout" in str(exc)` never matched libusb's actual message *"Operation
  timed out"*, so an idle device tore itself down ~100 ms after reaching READY and
  reconnected forever — rendering could never proceed. Now classified by
  `usb.core.USBTimeoutError` type (with an errno fallback). **This was the most
  likely cause of a "connects then dies" symptom after Zadig.**
- **`keys`/`media` actions were silent no-ops on Windows** (`actions.py`). The
  SendInput `INPUT` struct was 72 bytes; Windows requires exactly 40 on x64 or it
  injects nothing. Rewritten with the canonical union + fixed-width fields (40 bytes
  on any x64), return-value/last-error checks, extended-key flag, and no pywin32
  dependency (stdlib `ctypes` only).
- **Cross-thread teardown race** (`usb_link.py`): the input-listener thread could
  null the device handle while the main loop used it, crashing the daemon with an
  uncaught `AttributeError`. Teardown + state transitions are now serialized behind
  a state lock, and read/write/`_device_present` snapshot the handle.
- **Linux kernel-driver detach** before `claim_interface` (`usb_link.py`) — the
  reference behaviour that was documented but never implemented.

### Other fixes
- `cli.py`: `blit-screen`/`blit-key` now accept the `INITIALIZING` state (a fresh
  connect never reaches READY on its own, so both commands used to always fail with
  "device not ready"). `install-autostart` now registers `-m app.cli` run from the
  project dir (the old task ran `cli.py` as a script → broken relative imports).
- `webui`: `activate`/`PUT` report failure truthfully; image upload is
  path-traversal-safe (`secure_filename` + containment check); loopback-only Host
  guard against DNS-rebinding.
- `daemon.py`: single reentrant render lock across the main-loop / auto-switcher /
  action / Flask threads; blank (black) key images blitted on profile switch so a
  previous profile's key image doesn't linger; auto-switch map synced on reload/PUT.
- `profiles.py`: atomic `save_profiles` (temp file + `os.replace`).
- `protocol.py`: the bitmask key-event pattern is restricted to single-byte packets
  (the old bound was always true, so any junk packet was misread as a key press).
  **Still `[UNKNOWN]` until a real capture (Section H.3) — this only tightens the guess.**
- `pyproject.toml`: real build backend (`setuptools.build_meta`) + webui package-data.
- CI installs `requirements.txt`; dead-code/import cleanup; font caching.

### What this does NOT resolve (still open, unchanged)
Key-image addressing, key-event format, and brightness are still `[UNKNOWN]`. The
protocol tightening above is a safer guess, not a confirmed format — resolve these
via Section G/H on real hardware as originally planned.

---

## 9. Live Hardware Probe Addendum (2026-07-09)

- `tools/listen_hid.py` opens the non-keyboard DeathStalker HID collections and
  prints raw reports as hex. Use it before Zadig when pressing the LCD keys:
  `python tools\listen_hid.py`.
- A 10-second run opened four non-keyboard collections successfully but captured no
  reports without physical LCD-key presses during the window.
