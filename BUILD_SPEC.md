# BUILD_SPEC.md — Switchblade Reborn

Implementation spec. Read `RESEARCH.md` first, then work this file top to bottom.
Strategy/rationale lives in `PLAN.md`; you don't need it to build.

## 0. Rules for the implementer (read twice)

1. Work one phase at a time, in order. Finish the phase's **verify sweep** before
   starting the next phase. A verify sweep is a hard gate: if any item fails, fix it
   or STOP and report — never continue on top of a failed gate.
2. **Never** install/replace a driver on any interface other than the one identified
   as the Switchblade vendor interface in Phase 0. The other interfaces are the
   user's keyboard. Rebinding them bricks input until rollback.
3. Facts tagged **[SEED]**/**[UNKNOWN]** in RESEARCH.md must be verified on the real
   device before you rely on them. When hardware behavior contradicts this spec,
   trust the hardware, update `PROTOCOL.md`, and note the discrepancy.
4. Anything that needs the physical keyboard (captures, blit tests, driver work)
   requires the user at the machine. Prepare everything you can, then give the user
   exact step-by-step instructions and ask them to run/report.
5. Don't add features, options, or abstractions not listed here. Small and working
   beats general.
6. All temp/experiment scripts go in `tools/`, never in `app/`.
7. Do not copy code from GPL repos (see licensing note in RESEARCH.md).

## 1. Environment

- Windows 11, Python 3.11+ (64-bit).
- Create the project as a git repo with a venv. Dependencies (pin in
  `requirements.txt`): `pyusb`, `libusb-package` (ships libusb-1.0 DLL so the user
  doesn't hunt for it), `Pillow`, `hidapi`, `flask`, `psutil`, `pywin32`.
- Tools the user must install when asked (Phase 0): **Zadig** (driver binding),
  **Wireshark + USBPcap** (captures), **USBView** or USB Device Tree Viewer
  (enumeration).

## 2. Repository layout

```
switchblade-reborn/
  PLAN.md  BUILD_SPEC.md  RESEARCH.md  PROTOCOL.md   # PROTOCOL.md created in Phase 1
  requirements.txt
  app/
    usb_link.py        # transport: find/claim device, bulk read/write, reconnect
    protocol.py        # pure functions: build blit packets, parse key events
    renderer.py        # PIL image -> RGB565 frames, dirty-rect diffing
    input_listener.py  # reads key events, emits (key_index, pressed) callbacks
    actions.py         # execute action dicts: launch, keys, media, profile-switch
    profiles.py        # load/validate/save profiles.json, active-profile state
    daemon.py          # wires everything, main loop, state machine
    cli.py             # `python -m app.cli <command>`
    webui/             # Phase 3: Flask app + one HTML page
  profiles/
    profiles.json
    images/            # user key/screen images
  captures/            # .pcapng files, named per scenario (Phase 1)
  tools/               # throwaway probe/experiment scripts
  tests/               # pytest; protocol.py and renderer.py must be covered
```

Module dependency rule: `protocol.py` and `renderer.py` are pure (no USB, no
globals) so they are unit-testable without hardware. Only `usb_link.py` touches
pyusb. Only `daemon.py` wires modules together.

## 3. Safety: driver binding and rollback

The Switchblade vendor interface must be bound to WinUSB (via Zadig) so pyusb can
claim it. Composite-device rules:

1. In Zadig: Options → List All Devices, and **uncheck** "Ignore Hubs or Composite
   Parents" is NOT needed — you must select the **child interface** (it will show as
   `Razer DeathStalker Ultimate (Interface N)`), never the composite parent.
2. Only the interface number confirmed in Phase 0 as the vendor-specific
   (non-HID) interface gets WinUSB. HID keyboard interfaces are untouched.
3. **Rollback procedure** (test it in Phase 0 before ever using Zadig): Device
   Manager → find the device under Universal Serial Bus devices → Uninstall device
   (check "delete driver" if shown) → unplug/replug → Windows restores the default
   driver. Write this into the README for the user.
4. Runtime guard: `usb_link.py` must refuse to claim anything whose interface class
   is HID (class code 0x03).
5. Daemon startup guard: if a process named like `Razer Synapse`/`RzSynapse` is
   running, print a warning and exit (device contention).

---

## Phase 0 — Recon & safety

Goal: know the exact device topology; have capture tooling working; have rollback
proven. No app code yet except throwaway scripts in `tools/`.

Tasks:

1. Have the user plug the keyboard in and run USB Device Tree Viewer. Record for
   VID 0x1532 / PID 0x0114: every interface number, class/subclass/protocol, and
   every endpoint (address, direction, type, max packet size). Save as
   `PROTOCOL.md` section "Device map".
2. Identify the **vendor interface**: class 0xFF (vendor-specific), or at minimum
   the one that is not class 0x03 (HID). Expect bulk endpoints on it. Record which
   `MI_xx` it is.
3. Write `tools/enumerate.py` (pyusb): list the same info programmatically. It must
   work WITHOUT any driver change for listing (pyusb can enumerate without claiming).
4. User installs Wireshark + USBPcap. Do a 10-second test capture of any USB mouse
   to confirm the toolchain works.
5. Write the rollback instructions (section 3 above) into `README.md`. Have the
   user confirm Synapse 2.0 currently works (screen + keys alive) — that's our
   capture source and our "known good" restore state.

Verify sweep (all must pass):

- [ ] `PROTOCOL.md` device map lists every interface + endpoint with numbers.
- [ ] Vendor interface identified and it is NOT class 0x03.
- [ ] `tools/enumerate.py` output matches USB Device Tree Viewer.
- [ ] Test capture opens in Wireshark and shows URBs.
- [ ] Rollback procedure written in README and understood by user.
- [ ] Synapse currently drives the screen (user confirms visually).

## Phase 1 — Proof of life (HARD GATE)

Goal: three one-shot CLI commands working end to end:
`blit-screen <image>`, `blit-key <0-9> <image>`, `listen-keys`.

### 1A. Trackpad blit via seed protocol (try this first — may skip captures)

1. User closes Synapse fully (tray exit + kill `Rz*` processes), then uses Zadig to
   bind WinUSB to the vendor interface ONLY (per section 3).
2. Implement minimal `protocol.py`: `build_blit(x1, y1, x2, y2, rgb565_bytes) ->
   bytes` per the [SEED] header in RESEARCH.md (6 big-endian uint16: opcode 0x0001,
   rect, XOR checksum). First fetch and read the rzswitchblade C sources to resolve
   the checksum and rect-inclusivity questions — do not guess.
3. Implement minimal `usb_link.py` + `renderer.rgb565()` (PIL → RGB565 bytes; try
   big-endian pixel words first, byte-swap if colors come out wrong — e.g. pure red
   test image rendering as cyan/blue means swap).
4. `tools/blit_test.py`: send a full-screen 800×480 solid color, then a photo.
   User reports what the screen shows. Iterate: wrong colors → pixel byte order;
   garbage/offset rows → rect semantics or stride; nothing at all → likely a
   mode-switch/init packet is required → go to 1B.

### 1B. Captures (needed for keys + any missing init; skip nothing here if 1A failed)

1. Restore the Razer driver (rollback procedure), confirm Synapse works again.
2. Capture these scenarios with USBPcap, one file each, named exactly:
   - `captures/attach.pcapng` — start capture, plug device in, wait for Synapse to
     light it up. (Contains init/mode-switch.)
   - `captures/screen-change.pcapng` — change what the trackpad screen shows.
   - `captures/key-images.pcapng` — Synapse assigns a new image to one dynamic key.
   - `captures/key-press.pcapng` — press each of the 10 dynamic keys, in order,
     twice each. (Contains input events; note which direction/interface they appear
     on — vendor IN endpoint vs HID interrupt.)
   - `captures/brightness.pcapng` — change screen brightness in Synapse, min→max.
3. Analyze with pyshark or Wireshark manually. You know the blit header shape —
   search bulk OUT payloads starting with `00 01`. For key images, find the same
   header shape and record the addressing (rect beyond 800×480? different opcode?
   different endpoint?). Document every finding as hex dumps + field tables in
   `PROTOCOL.md` sections: "Init sequence", "Screen blit", "Key blit",
   "Key events", "Brightness".
4. Rebind WinUSB and implement what the captures showed. Repeat until 1A/1C pass.

### 1C. Dynamic keys + input

1. `blit-key N <image>`: renders image to the key resolution measured from the
   capture (expect 115×115 or 116×116 — record the real number) and sends it with
   the addressing discovered in 1B.
2. `listen-keys`: read the vendor IN endpoint; print raw hex of every packet, then
   decode to `key N down/up` once the pattern is clear. If nothing arrives there,
   listen on the HID interfaces with hidapi instead (no rebinding needed for HID)
   and document which path won.

Verify sweep (HARD GATE — user must visually confirm each):

- [ ] `blit-screen photo.jpg` shows the photo, correct colors, correct orientation.
- [ ] Second `blit-screen` call replaces the image (no reboot/replug needed).
- [ ] `blit-key 0..9` puts a distinct image on each of the 10 keys.
- [ ] `listen-keys` prints correct key index + down/up for all 10 keys.
- [ ] Device replug + `blit-screen` still works (init sequence, if any, is
      implemented — not dependent on Synapse having run since boot).
- [ ] `PROTOCOL.md` documents every packet type used, byte-by-byte, with one hex
      example each. Someone with no context could reimplement from it.
- [ ] Rollback to Razer driver verified once more, then WinUSB rebound. Both
      directions work.

## Phase 2 — Core daemon (MVP)

### Contracts

**profiles.json schema** (validate on load; reject with a clear message, never
crash):

```json
{
  "version": 1,
  "active_profile": "default",
  "settings": { "brightness": 80, "fps_cap": 15 },
  "profiles": {
    "default": {
      "screen": { "type": "image", "path": "images/bg.png" },
      "keys": [
        { "image": "images/discord.png", "label": "Discord",
          "action": { "type": "launch", "path": "C:/.../Discord.exe" } },
        { "image": null, "label": "", "action": null }
      ]
    }
  }
}
```

- `keys` is always length 10 (index = physical key 0–9).
- Action types (MVP, exactly these four):
  - `{"type": "launch", "path": "...", "args": "..."}` — `subprocess.Popen`, detached.
  - `{"type": "keys", "sequence": ["ctrl+shift+m"]}` — inject via pywin32
    `SendInput`; support modifiers + single keys; sequence items fire in order.
  - `{"type": "media", "key": "play_pause|next|prev|vol_up|vol_down|mute"}` —
    SendInput media virtual-key codes.
  - `{"type": "profile", "name": "..."}` — switch active profile.

**Device connection state machine** (in `daemon.py`; log every transition):

```
DISCONNECTED --device found--> CLAIMING --claim ok--> INITIALIZING
INITIALIZING --init sent, test blit ok--> READY
READY --usb error / unplug--> DISCONNECTED (release handle, retry every 2 s)
CLAIMING --claim fails--> ERROR_FATAL (another program owns it; log and exit)
```

- In READY: renderer may blit, input listener runs.
- Any `USBError` anywhere → transition to DISCONNECTED, never crash the process.

**Renderer contract:** holds `current` and `pending` 800×480 framebuffers. On
update, computes the changed bounding rect and blits only that. Full redraw on
entering READY. FPS cap from settings.

**Input dispatch:** key event → look up action in active profile → run in a worker
thread (an action must never block the USB read loop). Debounce: act on key-down
only, ignore repeats within 150 ms.

### Tasks

1. Flesh out `usb_link.py` (hotplug polling, claim/release, the state machine
   above), `profiles.py`, `actions.py`, `input_listener.py`, `renderer.py`.
2. `daemon.py`: on start → load profiles → connect → render active profile screen +
   key images → dispatch inputs. Clean shutdown on Ctrl+C (release interface).
3. `cli.py` commands: `run` (start daemon), `profile <name>`, `blit-screen`,
   `blit-key`, `validate` (check profiles.json), `status`.
4. pytest: `protocol.py` packet bytes against hex fixtures from PROTOCOL.md;
   renderer dirty-rect logic; profile schema validation (good + 5 bad fixtures).

Verify sweep:

- [ ] `pytest` green.
- [ ] Daemon runs 30+ minutes with the user using the PC normally; no crash, no
      dropped key events (user presses keys periodically).
- [ ] Unplug/replug while daemon runs → screen and keys restore within 5 s.
- [ ] Each of the 4 action types demonstrated working from a real key press.
- [ ] `profile <name>` switches images on screen + keys in under 1 s.
- [ ] Corrupt profiles.json → clear error message, no traceback spam, daemon exits
      cleanly (or keeps last good config if already running).

## Phase 3 — Control web UI

Flask app inside the daemon process, bound to `127.0.0.1:8377` only. One page.

1. GET `/` — page listing profiles, the 10 key slots of the selected profile
   (image thumbnail, label, action summary), screen background preview.
2. JSON API used by that page: `GET/PUT /api/profiles`, `POST /api/profiles/<name>/activate`,
   `POST /api/upload-image` (saves to `profiles/images/`, re-encodes via PIL to
   strip anything weird), `GET /api/status` (connection state, active profile).
3. Edits apply live: PUT profile → daemon re-renders affected keys/screen.
4. No auth (localhost only), no build tooling — one HTML file + vanilla JS.

Verify sweep:

- [ ] User edits a key image + action entirely from the browser and it works on
      hardware without restarting the daemon.
- [ ] Invalid uploads (non-image, 20 MB file) rejected with a message.
- [ ] Daemon still passes the Phase 2 sweep (regression check).

## Phase 4 — Better than Synapse

Order by value; each item independently shippable:

1. **Widgets on the trackpad screen.** `screen.type: "widget_board"` — a list of
   widgets with positions: `clock`, `cpu_ram` (psutil), `media_now_playing`
   (Windows GSMTC via `winsdk`/`winrt` — if that dependency fights back, ship
   clock+stats first). Re-render at 1 Hz through the existing dirty-rect renderer.
2. **Auto profile switch.** Map exe name → profile (`"auto_switch": {"code.exe":
   "coding"}`), poll foreground window via pywin32 every 2 s.
3. **Autostart.** `cli.py install-autostart` → creates a Task Scheduler entry
   (logon trigger, run hidden). `uninstall-autostart` reverses it.
4. **Keyboard backlight (optional).** Standard Razer HID feature reports (OpenRazer
   documents the 90-byte report format) on the HID interface via hidapi — no driver
   swap. Expose brightness in settings + web UI. If the report format for PID
   0x0114 isn't in OpenRazer's tables, capture Synapse's brightness slider and
   document it in PROTOCOL.md first.
5. **Touch input (stretch).** If captures show tap coordinates on an IN endpoint,
   add `tap` regions to widget boards (e.g. tap now-playing → play/pause).

Verify sweep:

- [ ] Clock/stats widget visibly updating; daemon CPU < 3 % average while idle.
- [ ] Focusing a mapped app switches profile; unfocusing switches back to default.
- [ ] Reboot → daemon auto-starts → screen alive with no user action.
- [ ] Full Phase 2 sweep re-run green (final regression).

---

## Definition of done (MVP = through Phase 2)

The user can: boot the PC with Synapse uninstalled, run one command, see their
chosen background on the trackpad screen and 10 chosen images on the keys, press a
key to launch an app / fire a macro / control media, and edit all of it in a JSON
file — with the device surviving replug. Everything beyond that is Phase 3+.
