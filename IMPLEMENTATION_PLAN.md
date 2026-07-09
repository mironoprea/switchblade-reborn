# IMPLEMENTATION_PLAN — Switchblade Reborn: Merge, Rebuild, Bind Driver, Run on Hardware

**Audience:** the coding model that will execute this. Do exactly what each step says.
**Author role:** advisor/planner. No code was applied by the planner — you apply it.
**Hardware:** Razer DeathStalker Ultimate, VID `0x1532` / PID `0x0114`, model RZ03-00790.
**OS:** Windows 11, Python 3.13. Repo: https://github.com/mironoprea/switchblade-reborn
**Starting point:** `build-fixes` branch (4 code/doc patches + `HANDOFF.md` + `switchblade-winusb.inf`).

---

> ## ⚠️ FRESH-AGENT START HERE (2026-07-09, PR #3 merged)
>
> **All code work through Section E is DONE and on `master`.** Two review passes
> shipped: PR #2 (build fixes) and PR #3 (transport / input-injection / web-API
> hardening — see `HANDOFF.md` §8). The `build-fixes` branch is gone.
>
> - **Do NOT re-apply Section C** — every edit there is already merged (and later
>   superseded/extended by PR #3).
> - **Do NOT follow Section D** — that branch/PR flow is complete.
> - **Section D's CI note is stale:** CI now installs `requirements.txt` (so
>   `pyusb`/`libusb-package`/`hidapi` are present and the transport tests run).
> - **Your actual next step is Section F (Zadig driver bind).** Everything before
>   it is complete; the forward plan **F → G → H.2/H.3 → I is still exactly right.**
> - Test baseline after PR #3 was **110 tests (108 pass, 2 `pyusb`-gated skips)**,
>   not 104. A later live hardware-probe hardening pass brings the local baseline
>   to **116 passing tests**.
>
> Sections A–E below are kept for history; read them for context, not as a to-do.

---

## EXECUTION STATUS (updated 2026-07-09)

| Section | Description | Status |
|---------|-------------|--------|
| A/B | Verify patches + read source | **Done** — all 3 patches verified correct |
| H.1 | Mine FxChiP/rzswitchblade source | **Done** — header/checksum/init confirmed; key addressing + brightness not in FxChiP |
| C.1 | Delete malformed INF | **Done** — `switchblade-winusb.inf` removed |
| C.2 | Fix PROTOCOL.md device map | **Done** — 4-interface topology, [CONFIRMED] |
| C.3 | Add init-sequence hook | **Done** — `Daemon._initialize_device()` no-op added |
| C.4 | Fix bulk IN read length | **Done** — 64 → 512 in input_listener.py + listen_keys.py |
| C.5 | Add I/O lock in UsbLink | **Done** — `threading.Lock` in write() + read() |
| D | Review, commit, push, PR, merge | **Done** — PR #2 (build fixes) + PR #3 (review hardening) merged to master |
| E | Rebuild venv, run tests, validate | **Done** — 116 tests pass, profiles valid, libusb loads |
| — | Second review pass: transport/actions/web-API hardening | **Done** — PR #3; full detail in HANDOFF.md §8 |
| F | Bind WinUSB via Zadig | **Not started** — requires GUI + physical hardware **← fresh agent starts here** |
| G | Hardware bring-up (blit test, keys) | **Not started** — requires Section F first |
| H.2 | USB captures (if needed) | **Not started** — must be done before Section F |
| H.3 | Key-event format resolution | **Not started** — requires hardware or captures |
| I | Final acceptance checklist | **Not started** — requires all above |

**FxChiP findings (H.1):** Header format (6 × big-endian uint16, opcode 0x0001, XOR
checksum) confirmed matching. Rectangle is inclusive. No init sequence needed (claim
+ blit immediately). Key size may be 116×116 (README says 116, code uses 115). FxChiP
sends header and payload as **two separate** bulk transfers; our code concatenates
them (noted as diagnostic fallback in PROTOCOL.md and Section G.5). Key-image
addressing and brightness are not in FxChiP — remain [UNKNOWN].

---

## 0. READ THIS FIRST — critical sequencing

There are two things that MUST happen in the right order, or you will lose the ability to do them:

1. **USB captures of the Razer stack must be done BEFORE you run Zadig.**
   Right now interface 3 is bound to the **Razer driver** (`oem16.inf` / `rzhnet.inf`). That is the only
   state in which Razer Synapse (or any Razer SDK harness) can drive the device and produce *reference*
   USB traffic (init sequence, key-image writes, key presses, brightness). The moment you bind **WinUSB**
   with Zadig, the Razer driver is gone and you can no longer capture reference traffic without rolling back.
   **If you need captures at all (Section H), do them before Section F.**

2. **Before spending any time on captures, mine the FxChiP/rzswitchblade source (Section H.1).**
   `RESEARCH.md` states that https://github.com/FxChiP/rzswitchblade is a Linux libusb library that
   **explicitly lists the DeathStalker Ultimate as supported**. Its C source almost certainly contains the
   exact init sequence, key-image addressing, and brightness bytes. Porting those constants is far cheaper
   and more reliable than USB captures and may make captures unnecessary. Do H.1 first.

**Recommended overall order:** Section A/B (verify + read) → H.1 (mine FxChiP, cheap, no hardware) →
C (code fixes) → D (merge) → E (rebuild) → **H.2 captures IF still needed, while Razer driver is bound** →
F (Zadig) → G (bring-up) → I (final run). If you decide no captures are needed, skip straight from E to F.

---

## 1. Verdict on the 3 patches (verified against source on `build-fixes`)

All three patches are **correct and were verified on hardware** per the handoff (device is detected and
interface 3 is identified). Details:

| Patch | File | Verdict | Notes |
|-------|------|---------|-------|
| 1 | `app/usb_link.py` | **Correct & complete** | `libusb_package.get_libusb1_backend()` is a real API; `_BACKEND` is passed to `usb.core.find`. If the import fails, `_BACKEND=None` and pyusb falls back to auto-discovery (harmless). Confirmed working: the device is discovered. |
| 2 | `tools/enumerate.py` | **Correct & complete** | Same pattern, same reasoning. |
| 3 | `app/daemon.py` | **Correct, but see 2.5** | Adds `INITIALIZING` import and `if state == INITIALIZING: self.link.mark_ready()` in the main loop. This unblocks the state machine. There is a harmless 1-cycle (~66 ms) delay before the `READY` branch runs because `state` is captured at the top of the loop; not a bug. The real gap is that it transitions to READY **without sending any init sequence** — fine for now, but wire in the init hook per Section C.3 so captured init bytes have a home. |

**Conclusion:** the patches do not need to change to unblock the build. The blocker is purely the driver
binding (Section F). Do not rewrite the patches; only add the refinements in Section C.

---

## 2. Bugs and omissions the previous attempt missed (fix these)

### 2.1 `switchblade-winusb.inf` is malformed — delete it
The custom INF contains a broken registry line:

```
[WinUsb_AddReg]
HKR,,DriverFl
```

`HKR,,DriverFl` is truncated garbage (it should be a `DeviceInterfaceGUIDs` entry). The INF approach
already failed (Windows ranks the Razer driver higher) and you are switching to **Zadig**, which does not
use this file. **Action:** delete `switchblade-winusb.inf`. Do not try to repair it.

```powershell
git rm switchblade-winusb.inf
```

### 2.2 `PROTOCOL.md` device map is stale/wrong — correct it to confirmed hardware
`PROTOCOL.md` lists only 3 interfaces and says the vendor interface is **interface 2**. The confirmed
hardware (from `HANDOFF.md`) has **4 interfaces**, the vendor interface is **interface 3**, and interfaces
0/1/2 are all HID (class `0x03`). The code auto-picks the first class-`0xFF` interface so it still works,
but the doc is misleading. **Action:** replace the "Device map" table in `PROTOCOL.md` with the confirmed
topology below and remove the `[SEED]` tag on it (it is now `[CONFIRMED]`):

```
| Interface | Class | Subclass | Protocol | Endpoints | Purpose |
|-----------|-------|----------|----------|-----------|---------|
| 0 | 0x03 (HID) | 0x01 | 0x02 | Interrupt IN 0x81 (8B) | Standard keyboard |
| 1 | 0x03 (HID) | 0x00 | 0x01 | Interrupt IN 0x82 (16B) | HID media/consumer |
| 2 | 0x03 (HID) | 0x01 | 0x01 | Interrupt IN 0x83 (8B) | HID system control |
| 3 | 0xFF (Vendor) | 0xF0 | 0x00 | Bulk OUT 0x01 (512), Bulk OUT 0x02 (512), no bulk IN observed | Switchblade UI |
```

### 2.3 Key events may NOT arrive on the vendor IN endpoint (design risk)
`RESEARCH.md` explicitly warns: AIDA64's native implementation *never got key input working* on the vendor
IN endpoint (0x02); events "might instead arrive as HID input reports on interface 0/1." The current
`app/input_listener.py` **only** reads the vendor IN endpoint via `link.read()`. If no key events show up
there during bring-up (Section G), the fix is to read HID reports from interface 0 or 1 with `hidapi`
(already a dependency). Do not build this preemptively — but know it is the most likely functional gap and
Section H.3 covers how to resolve it.

### 2.4 Bulk IN read length is smaller than the endpoint's max packet (overflow risk)
`app/input_listener.py` and `tools/listen_keys.py` call `link.read(length=64, ...)`, but the vendor IN
endpoint's max packet size is **512** (confirmed). If the device ever sends a packet larger than 64 bytes,
libusb raises an overflow error. **Action:** change these reads to request 512 bytes (see Section C.4).

### 2.5 Daemon has no init hook and no I/O lock (two small robustness gaps)
- The daemon writes blits from the main loop while the `InputListener` thread reads from the same device
  handle. Concurrent bulk read (EP 0x02) + write (EP 0x01) on different endpoints is normally fine, but the
  error paths in `read()`/`write()` both call `_release()` and mutate `self.state`/`self.dev` with no lock —
  a race if both threads error at once. Add a lock (Section C.5). Low severity; do it for safety.
- There is no place to send an init sequence once you discover it. Add the hook now (Section C.3) so
  captured init bytes drop in cleanly.

### 2.6 Endian is hard-coded to "big" in the daemon path (minor)
`build_screen_blit`/`render_image_to_framebuffer` default to `endian="big"`. The `--endian little` toggle
only exists in `tools/blit_test.py`. If colors come out swapped on hardware, the daemon has no runtime
switch. This is acceptable for first bring-up (use `blit_test.py --endian little` to test), but if little
matters, wire `settings.pixel_endian` from `profiles.json` through to the render calls. Deferred; note only.

---

## 3. (Section C) Code changes to apply — exact edits

Apply these on the `build-fixes` branch (or a new branch off it — see Section D). Each shows the exact
current text and the replacement. Keep changes surgical; do not reformat surrounding code.

### C.1 Delete the malformed INF
```powershell
git rm switchblade-winusb.inf
```

### C.2 Fix the `PROTOCOL.md` device map
Open `PROTOCOL.md`, find the "## Device map" section and its `[SEED]` table, and replace the table with the
confirmed one from Section 2.2. Change the `**[SEED]**` note above it to `**[CONFIRMED]** on real hardware
(see HANDOFF.md). Vendor interface = interface 3, class 0xFF.`

### C.3 Add an init-sequence hook in the daemon
This gives captured/ported init bytes a home and does nothing until you fill it in.

In `app/daemon.py`, the current main-loop block (around line 703) reads:

```python
            if state == INITIALIZING:
                self.link.mark_ready()
```

Replace with:

```python
            if state == INITIALIZING:
                self._initialize_device()
                self.link.mark_ready()
```

Then add this method to the `Daemon` class (place it right after `_on_device_ready`):

```python
    def _initialize_device(self) -> None:
        """Send the device init/mode-switch sequence, if any.

        [UNKNOWN] until resolved from FxChiP/rzswitchblade source or a USB capture
        (see IMPLEMENTATION_PLAN.md Section H). Currently a no-op: the device is
        assumed to accept blits directly after claim. Fill this in with the exact
        init bytes once known, e.g.:

            for packet in protocol.INIT_SEQUENCE:
                self.link.write(packet)
        """
        return
```

Do **not** invent init bytes. Leave it a no-op until Section H resolves the real sequence.

### C.4 Read the full max-packet size (fix overflow risk)
In `app/input_listener.py`, `_run()` currently has:

```python
                data = self._link.read(length=64, timeout=self._read_timeout)
```

Change `length=64` to `length=512`:

```python
                data = self._link.read(length=512, timeout=self._read_timeout)
```

In `tools/listen_keys.py`, change:

```python
                data = link.read(length=64, timeout=500)
```
to
```python
                data = link.read(length=512, timeout=500)
```

### C.5 Add an I/O lock in `UsbLink` (thread-safety)
In `app/usb_link.py`, add `import threading` at the top (next to `import time`). In `UsbLink.__init__`,
after `self._last_try = 0.0`, add:

```python
        self._io_lock = threading.Lock()
```

Wrap the bodies of `write()` and `read()` in `with self._io_lock:`. Concretely, in `write()` change:

```python
        try:
            total = 0
            offset = 0
```
to:
```python
        try:
            with self._io_lock:
                total = 0
                offset = 0
```
and indent the rest of the `try` body one level (through `return total`). Do the same for `read()`:
wrap the `try` body (from `data = self.dev.read(` through `return bytes(data)`) in `with self._io_lock:`.
Keep the existing `except` blocks at their current indentation (outside the `with`). Run the tests after
this edit — indentation mistakes here are the most likely error.

### C.6 Do NOT change anything else
The protocol builder, checksum, renderer, profiles, web UI, actions, and auto-switch are correct and
covered by 104 passing tests. Leave them alone.

---

## 4. (Section D) Get the fixes reviewed and merged

The `build-fixes` branch is currently only on the remote; your local `master` has just the planning docs.

1. Fetch and check out the branch, then create a review branch off it:
   ```powershell
   git fetch origin
   git checkout build-fixes
   git checkout -b build-fixes-review
   ```
2. Apply all Section C edits on `build-fixes-review`.
3. Run the full test suite (Section E.3). All 104 must pass.
4. Run the built-in review skill on the diff (optional but recommended): `/code-review`.
5. Commit with a clear message:
   ```powershell
   git add -A
   git commit -m "Fix INF, protocol doc topology, init hook, IN read size, io-lock"
   ```
   (End the commit body with the Co-Authored-By trailer the harness requires.)
6. Push and open a PR into `master`:
   ```powershell
   git push -u origin build-fixes-review
   gh pr create --base master --head build-fixes-review --title "Build fixes + Windows driver bring-up" --body "See IMPLEMENTATION_PLAN.md and HANDOFF.md"
   ```
7. Merge after CI is green. **Note (updated PR #3):** CI (`.github/workflows/ci.yml`) now installs the full
   `requirements.txt` (plus `pytest`), so `pyusb`/`libusb-package`/`hidapi` are present. The transport
   timeout tests in `tests/test_usb_link.py` run on CI as a result (they skip locally only if `pyusb` is
   absent). Hardware-dependent paths (claiming the device, real blits) are still not CI-tested.

**Do not** commit the local `venv/` (it is gitignored) or any `captures/*.pcapng` unless asked.

---

## 5. (Section E) Rebuild the project

From the repo root, in PowerShell:

1. Create/refresh the venv and install deps:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   pip install pytest
   ```
   If `.\venv\Scripts\Activate.ps1` is blocked by execution policy, run:
   `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (process-scoped, safe).
2. Confirm the libusb backend loads (this is the thing Patch 1 fixes):
   ```powershell
   python -c "import libusb_package; print(libusb_package.get_libusb1_backend())"
   ```
   Expect a non-`None` backend object printed.
3. Run tests and validate profiles:
   ```powershell
   python -m pytest tests/ -q
   python -m app.cli validate
   ```
   Expect `104 passed` and `valid`.

---

## 6. (Section F) Bind WinUSB to interface 3 with Zadig

**Prerequisite:** if you are doing captures (Section H.2), do them BEFORE this step. Once WinUSB is bound,
Synapse/Razer can no longer drive the device.

**Also:** fully exit Razer Synapse and kill `Rz*` processes first — the daemon refuses to start while
Synapse runs, and Zadig binding is cleaner with nothing holding the device.
```powershell
Get-Process | Where-Object { $_.Name -like "Rz*" -or $_.Name -like "*Razer*" } | Stop-Process -Force -ErrorAction SilentlyContinue
```

Steps (this is a GUI tool; there is no reliable CLI equivalent for forcing the bind):

1. Download Zadig from https://zadig.akeo.ie/ and run it **as Administrator**.
2. Menu: **Options → List All Devices** (checkbox). This reveals composite-child interfaces.
3. In the dropdown, find the entry for the DeathStalker Ultimate whose **USB ID** shows interface 3.
   The exact instance ID confirmed on this hardware is:
   `USB\VID_1532&PID_0114&MI_03\6&3b17fa3&0&0003`
   In Zadig the target row will read something like **"Razer DeathStalker Ultimate (Interface 3)"**.
   Cross-check: the driver currently shown for it should be the Razer driver (e.g. `rzhnet` / provider
   Razer), and its USB ID must contain **`MI_03`**.
4. **CRITICAL SAFETY:** Only ever select the **Interface 3 / MI_03** row. Never touch interfaces 0, 1, or 2
   — those are your keyboard and media keys (HID, class 0x03). Binding WinUSB to them will disable your
   keyboard input.
5. In the target-driver box (right of the green arrow), select **WinUSB** (default is fine; libusbK also
   works but standardize on WinUSB).
6. Click **Replace Driver** (or "Install Driver"). Wait for success. This takes a few seconds.
7. Verify in **Device Manager**: the device should now appear under **Universal Serial Bus devices** as
   "Razer DeathStalker Ultimate (Interface 3)" with driver `WinUSB`. Interfaces 0–2 must still be under
   **Keyboards / HID** unchanged.

**Verify libusb can now claim it:**
```powershell
python tools\enumerate.py
```
Expect it to print all interfaces including `Interface 3: class=Vendor-specific (0xFF)` with
`Endpoint 0x01 (OUT, bulk, max_pkt=512)` and `Endpoint 0x02 (OUT, bulk, max_pkt=512)`. If enumerate prints
the tree without the previous "Operation not supported" claim error, the bind worked.

**Rollback (if you bound the wrong interface or want Razer back):**
1. Device Manager → find the affected device → right-click → **Uninstall device** → check **"Delete the
   driver software for this device"** → OK.
2. Unplug the keyboard, wait 5 seconds, replug.
3. Windows restores the default driver automatically. If a HID interface was wrongly bound and the keyboard
   is dead, do this from an on-screen keyboard or a second USB keyboard.

---

## 7. (Section G) First hardware bring-up — prove blits render

Do these in order. Stop and diagnose at the first failure.

1. **Enumerate** (already done in F): confirms claim works.
2. **Static screen blit** — the single most important test. Put any 800×480 image at a known path (or use
   an existing `profiles/images/bg.png`) and run:
   ```powershell
   python tools\blit_test.py profiles\images\bg.png
   ```
   - If the image appears on the trackpad LCD: the blit header, checksum, RGB565, and endpoint are all
     correct. **This is the milestone that proves the protocol.**
   - If nothing appears: try `--endian little`:
     ```powershell
     python tools\blit_test.py profiles\images\bg.png --endian little
     ```
   - If still nothing: the device likely needs an **init sequence** first (Section H). Also try sending the
     whole packet as one `dev.write()` instead of the 512-byte manual chunks (see G.5).
   - If colors are wrong/garbled but an image appears: it is an endian or pixel-format issue — the `little`
     toggle usually fixes swapped colors.
3. **Key image blit** — test one dynamic key:
   ```powershell
   python -c "from app.usb_link import UsbLink; from app import protocol; from app.renderer import render_key_image_to_rgb565; l=UsbLink(); [l.poll() for _ in range(10)]; l.mark_ready(); l.write(protocol.build_key_blit(0, render_key_image_to_rgb565('profiles/images/key0.png'))); l.disconnect()"
   ```
   - If key 0's LCD shows the image: the `y=480` / 115×115 addressing hypothesis is correct.
   - If the key image appears in the wrong place, wrong key, or corrupts the main screen: the addressing is
     wrong — resolve via Section H.2 (key-image capture) or H.1 (FxChiP source).
4. **Key events** — run the listener and press the 10 LCD keys:
   ```powershell
   python tools\listen_keys.py
   ```
   - If `RAW: ...` lines print when you press LCD keys: note the exact bytes; feed them to Section H.3 to
     confirm/fix `parse_key_event`.
   - If nothing prints on any LCD key press: key events are almost certainly on the **HID** interfaces, not
     the vendor endpoint (see 2.3). Go to Section H.3, HID path.
5. **Chunking fallback (only if G.2 fails):** In `app/usb_link.py`, `write()` currently loops sending
   `max_out_packet` (512-byte) chunks. Some devices want the entire logical blit as a single bulk transfer.
   As a diagnostic, temporarily replace the chunk loop with a single `self.dev.write(self.info.out_endpoint,
   data, timeout=USB_TIMEOUT)` and retry G.2. If that renders, keep the single-write form. Do not make this
   change unless chunked writes fail.
6. **Full daemon:**
   ```powershell
   python -m app.cli run
   ```
   Expect logs: `CLAIMING` → `INITIALIZING` → `READY` → `Device ready. Rendering active profile.` The web
   UI at http://127.0.0.1:8377 should load. The active profile's screen and key images should appear.

---

## 8. (Section H) Resolve the `[UNKNOWN]` protocol gaps

There are four unknowns: **init sequence**, **key-image addressing**, **key-event format**, **brightness**.
Resolve them cheapest-first.

### H.1 FIRST: mine FxChiP/rzswitchblade (no hardware, no captures)
`RESEARCH.md` names https://github.com/FxChiP/rzswitchblade as a libusb library that **supports the
DeathStalker Ultimate**. Its C source is the highest-value reference. Do this:

1. Read these files in that repo (names per RESEARCH.md): `src/rzsblit_proto.c`, `src/rzsbl*` headers, and
   any `README`. Look specifically for:
   - **Init / mode-switch:** any control transfer or bulk write sent right after opening the device, before
     the first blit (e.g. a "set mode", "start", or magic packet). Port the exact bytes into
     `protocol.INIT_SEQUENCE` (a list of `bytes`) and have `Daemon._initialize_device()` (Section C.3) send
     them.
   - **Key-image addressing:** how it computes the rectangle/offset for each of the 10 keys. Confirm whether
     it uses the "keys below the screen at y=480, 115×115" model (matches current `protocol.key_rect`) or a
     separate opcode/endpoint. Update `KEY_IMAGE_SIZE`, `KEY_Y_OFFSET`, and `key_rect()` to match.
   - **Brightness:** any command it exposes for backlight/screen brightness. Capture the exact opcode/report
     and add a `build_brightness(level)` function + a CLI/daemon call.
   - **Checksum/endianness:** confirm the XOR checksum and big-endian header match — the current code claims
     this came from rzswitchblade, so it should already agree. If FxChiP uses little-endian pixels, flip the
     default.
2. This is a clean-room reimplementation: derive **constants and byte sequences** from the reference, write
   your own Python. Do not copy GPL C code verbatim into the MIT repo. Document each ported fact in
   `PROTOCOL.md` with a `[PORTED from FxChiP/rzswitchblade]` tag and change the relevant `[UNKNOWN]` tags.
3. Re-test on hardware (Section G) after each ported change.

If H.1 fully explains init + key addressing + brightness (likely), you may not need captures at all — go to
Section F/G and finish. Do captures only for whatever remains unresolved.

### H.2 Captures — ONLY if H.1 leaves gaps, and ONLY while the Razer driver is still bound
**Do this before Section F (Zadig).** You need the Razer driver + something that drives the device. Options,
best first:
- **Best:** a working install of Razer Synapse 2.0 (the discontinued app this project replaces). If you
  still have it, it will perform init, assign key images, and receive key presses — perfect reference.
- **Alternative:** a Razer SDK harness (`RzSwitchbladeSDK2.dll`) as noted in RESEARCH.md, used only to drive
  the device while you capture. Unstable but sufficient for a capture.
- If you have neither, you cannot capture reference traffic; fall back to empirical bring-up (Section G)
  plus H.1, and accept that key events may stay unresolved until you find a driver source.

**Capture tooling (Windows):**
1. Install **Wireshark** (https://www.wireshark.org/) and, during install, enable **USBPcap**
   (Wireshark's Windows USB capture driver). Reboot if prompted.
2. Launch Wireshark **as Administrator**. In the capture interface list, pick the **USBPcap** interface for
   the **root hub the keyboard is on**. If unsure which hub, unplug/replug the keyboard and watch which
   USBPcap interface shows traffic, or use the USBPcapCMD device picker to select the DeathStalker.
3. Set a display filter to isolate this device. First find its USBPcap bus/device address in the capture,
   then filter, e.g.:
   ```
   usb.idVendor == 0x1532 && usb.idProduct == 0x0114
   ```
   or, once you know the address, `usb.device_address == N`. To see only vendor bulk traffic, add
   `usb.transfer_type == 0x03` (bulk) and filter on endpoints `0x01` (OUT) and `0x02` (IN).

**Capture scenarios (run each, save a separate `.pcapng` into the repo's `captures/` folder):**
- `01-attach-init.pcapng`: start capture, then plug in the keyboard (or start Synapse). Captures the init /
  mode-switch sequence → resolves the **init** unknown. Look for the first bulk-OUT or control transfers to
  interface 3 before any large pixel payload.
- `02-set-key-image.pcapng`: with capture running, use Synapse to assign a distinct image to one dynamic
  key. The bulk-OUT payload's header reveals the **key-image addressing** (compare the x1/y1/x2/y2 in the
  12-byte header against the `y=480, 115×115` hypothesis).
- `03-key-press.pcapng`: press each of the 10 LCD keys. Watch the HID interrupt IN endpoints
  (0x81/0x82/0x83), plus any vendor IN endpoint if a capture shows one. Wherever the bytes change per key
  press is the **key-event** source and format.
- `04-brightness.pcapng`: change screen brightness in Synapse. The differing transfer is the **brightness**
  command.

**Decoding a captured blit header (sanity check your parser):** the first 12 bytes of a bulk-OUT to EP 0x01
should be six big-endian uint16: `opcode(0x0001) x1 y1 x2 y2 checksum`, where
`checksum = opcode ^ x1 ^ y1 ^ x2 ^ y2`. If the captured headers match this, the current `build_blit` is
confirmed. If not, update `HEADER_FORMAT`, the opcode, or the checksum in `app/protocol.py` to match.

### H.3 Key-event format resolution (the highest-risk unknown)
Use the bytes from `03-key-press.pcapng` (or from `tools/listen_keys.py` in Section G.4):

- **If events appear on a vendor IN endpoint:** map the raw bytes to key index + up/down and make
  `protocol.parse_key_event()` match exactly. The current function tries two hypotheses (1-indexed byte +
  flag, or bitmask); replace the guesswork with the confirmed layout and delete the dead hypothesis. Add a
  unit test in `tests/test_protocol.py` using a real captured packet as the fixture.
- **If events appear on a HID interface (0x81/0x82/0x83) instead** (RESEARCH.md says AIDA64 never got vendor
  key input working — treat this as the likely case): implement a HID reader. Concretely:
  1. Add a `HidKeyListener` (new small module or a branch in `app/input_listener.py`) that uses `hidapi`
     (already a dependency) to open the DeathStalker by VID/PID on the interface that carries the LCD-key
     reports, and reads input reports in a loop.
  2. Parse the report bytes (from the capture) into a `protocol.KeyEvent`.
  3. Feed events through the same `Daemon._on_key_event` callback, so actions still fire.
  4. Note: HID interfaces do NOT require Zadig/WinUSB — `hidapi` reads them via the OS HID stack, which
     coexists with the keyboard. Do not unbind the HID driver.
  5. Gate which path is active behind a config flag or auto-detect (try vendor endpoint; if silent for N
     seconds, fall back to HID).

Document the resolved format in `PROTOCOL.md` (change `[UNKNOWN]` → `[CONFIRMED]`) and commit the `.pcapng`
files to `captures/` only if the user wants them retained (they can be large; ask first).

---

## 9. (Section I) Final acceptance checklist

The keyboard is "actually running" when all of these pass:

- [ ] `python tools\enumerate.py` lists interface 3 as Vendor-specific with bulk OUT EPs 0x01/0x02 (WinUSB bound).
- [ ] `python tools\blit_test.py <image>` renders the image on the trackpad LCD with correct colors.
- [ ] A key-image blit renders on the correct dynamic key at the correct position.
- [ ] Pressing an LCD key produces a parsed `KeyEvent` (via vendor endpoint or HID per H.3) and triggers its
      configured action.
- [ ] `python -m app.cli run` reaches `READY`, renders the active profile's screen + all key images, and the
      web UI at http://127.0.0.1:8377 loads and can switch profiles.
- [ ] Unplug/replug the keyboard: the daemon logs `DISCONNECTED` then reconnects to `READY` within a few
      seconds (hotplug works).
- [ ] All tests still pass (`python -m pytest tests/ -q`; currently 110 — 108 pass + 2 pyusb-gated skips),
      plus any new capture-fixture tests.
- [ ] `PROTOCOL.md` no longer contains `[UNKNOWN]` for any gap you resolved; each resolved fact is tagged
      `[CONFIRMED]` or `[PORTED …]`.

---

## 10. Safety reminders (do not skip)

- **Never bind WinUSB to interfaces 0, 1, or 2.** Only interface 3 (`MI_03`, class 0xFF). Binding a HID
  interface disables your keyboard.
- **Exit Razer Synapse before running the daemon** — the daemon exits if it detects `Rz*`/Synapse processes,
  and two programs cannot own the vendor interface at once.
- **Captures before Zadig** — you cannot capture Razer reference traffic after WinUSB is bound.
- **Clean-room only** — port *constants/byte sequences* from GPL references (FxChiP), never source code, into
  this MIT-licensed repo. Tag every ported fact in `PROTOCOL.md`.
- **Rollback is always available** — Device Manager → Uninstall device (+ delete driver) → replug restores
  the Razer driver.
```
