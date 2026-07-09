# Switchblade Reborn

Standalone Windows control app for the Razer DeathStalker Ultimate Switchblade UI
(4" 800×480 touch LCD + 10 LCD dynamic keys) — replaces discontinued Razer Synapse 2.0.

No Razer login, no cloud, no Synapse process required.

## Current Status

| Area | Status | Notes |
|------|--------|-------|
| Build & tests | Working | all tests pass (157), profiles valid, libusb backend loads |
| Code hardening (review) | Done | Transport/actions/web-API bugs fixed in PR #3; see HANDOFF.md §8 |
| USB transport (pyusb + libusb) | Working | Device detected, interface 3 identified, blit OUT endpoint selection patched |
| Protocol layer (blit, checksum) | Working | Header/checksum confirmed; screen blits use little-endian RGB565 and header+single-payload transfers |
| Init sequence | Resolved | No init needed per FxChiP source; no-op hook in place for future use |
| Display backends | Working | `auto` uses the Razer SDK backend when available; `usb` keeps the direct WinUSB bulk path |
| Driver binding (Zadig) | Optional by backend | Required only for `--backend usb`; the SDK backend works with the Razer driver |
| Hardware bring-up | Working via SDK backend | Main LCD + physical LCD key images render; physical key events captured over HID |
| Direct USB key image addressing | Implemented from trace | SDK client trace shows key writes use bulk OUT 0x02 with captured rectangles |
| Key event format | Working | Physical LCD keys report over HID as `04 50`..`04 59`, release `04 00` |
| Brightness control | Unknown | Not in FxChiP; may need Razer HID feature report |
| Web UI, profiles, actions, widgets | Working | All functional, covered by tests |

See `HANDOFF.md` for full build history and `IMPLEMENTATION_PLAN.md` for the
step-by-step guide to completing the remaining hardware steps.

## Quick Start

```powershell
# Create a virtual environment and install dependencies
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Validate your profiles
python -m app.cli validate

# Start the daemon (screen + keys + web UI).
# On Windows with the Razer SDK installed, auto uses the SDK backend.
python -m app.cli run
```

The web UI is available at `http://127.0.0.1:8377`.

## CLI Commands

```
python -m app.cli run                 # Start the daemon (screen, keys, web UI)
python -m app.cli profile <name>      # Switch active profile
python -m app.cli blit-screen <image>  # Blit an image to the trackpad screen
python -m app.cli blit-key <N> <img>   # SDK backend in auto/sdk; key OUT 0x02 in usb mode
python -m app.cli validate            # Validate profiles.json
python -m app.cli status              # Show connection state and active profile
python -m app.cli install-autostart    # Install Windows Task Scheduler autostart
python -m app.cli uninstall-autostart  # Remove the autostart entry
python tools\listen_hid.py             # Diagnostic: print raw HID reports
python tools\adb_photo.py --output captures\phone\keyboard.jpg
python tools\capture_usbpcap.py --name 02-set-key-image  # Capture USBPcap roots
python tools\analyze_capture.py captures\02-set-key-image-usbpcap6.pcap
```

### Display Backends

`--backend auto` is the default. On Windows, if
`C:\ProgramData\Razer\SwitchBlade\SDK\RzSwitchbladeSDK2.dll` is installed, the app
starts a persistent 32-bit SDK bridge and renders both the 800x480 touchpad and
all ten physical LCD keys through the official Razer SDK. This is the verified
path on the current hardware.

Use `--backend usb` only when interface 3 (`MI_03`) is bound to WinUSB and you
want the direct bulk protocol path. That path renders the main touch LCD through
bulk OUT `0x01` and physical key images through bulk OUT `0x02` using rectangles
captured from the official SDK client.

## Features

- **Trackpad screen**: display any image on the 800×480 LCD.
- **Physical LCD keys**: images render through the SDK backend; key presses are read over HID and can trigger actions.
- **Actions**: launch apps, inject keyboard shortcuts, control media, switch profiles.
- **Profiles**: named sets of key images + actions, switchable at runtime.
- **Web UI**: edit profiles, upload images, switch profiles from your browser.
- **Screen widgets**: clock, CPU/RAM monitor, now-playing (Phase 4).
- **Auto profile switch**: switch profiles based on foreground app (Phase 4).
- **Autostart**: run automatically on login (Phase 4).
- **Hotplug**: device survives unplug/replug — auto-reconnects within seconds.

## Configuration

Edit `profiles/profiles.json` to configure:

```json
{
  "version": 1,
  "active_profile": "default",
  "settings": { "brightness": 80, "fps_cap": 15 },
  "profiles": {
    "default": {
      "screen": { "type": "image", "path": "images/bg.png" },
      "keys": [
        { "image": "images/app.png", "label": "My App",
          "action": { "type": "launch", "path": "C:/Path/app.exe" } },
        ...
      ]
    }
  }
}
```

### Action Types

| Type | Fields | Description |
|------|--------|-------------|
| `launch` | `path`, `args` | Launch an application |
| `keys` | `sequence` | Inject keyboard shortcuts (e.g. `["ctrl+shift+m"]`) |
| `media` | `key` | Media control: `play_pause`, `next`, `prev`, `vol_up`, `vol_down`, `mute` |
| `profile` | `name` | Switch to a named profile |

### Screen Types

| Type | Description |
|------|-------------|
| `image` | Display a static image (`path` field) |
| `widget_board` | Display live-updating widgets (`widgets` array) |

Widget types: `clock`, `cpu_ram`, `media_now_playing`.

## Driver Setup (Zadig)

The direct USB backend requires the Switchblade vendor interface (**interface 3**,
class 0xFF) to be bound to WinUSB so pyusb can access it. The default SDK backend
does not require this; it expects MI_03 to use the original Razer driver.

1. Fully exit Razer Synapse and kill `Rz*` processes.
2. Download [Zadig](https://zadig.akeo.ie/) and run as Administrator.
3. Options → List All Devices (checkbox).
4. Find **Razer DeathStalker Ultimate (Interface 3)** — the one whose USB ID
   contains `MI_03`. Cross-check: its driver should currently be the Razer driver.
5. Set the target driver to **WinUSB** and click Replace Driver.
6. **CRITICAL:** Only select the Interface 3 / `MI_03` row. Never touch interfaces
   0, 1, or 2 — those are HID (keyboard, media, system control). Binding WinUSB
   to them will disable your keyboard.
7. Verify: `python tools\enumerate.py` should list interface 3 as Vendor-specific
   with bulk OUT endpoints 0x01/0x02, then the CLI/daemon should claim the
   interface without the previous `Operation not supported` error.

### Rollback Procedure

If you need to restore the original driver:

1. Open Device Manager.
2. Find the device under "Universal Serial Bus devices".
3. Right-click → Uninstall device (check "delete driver" if shown).
4. Unplug the keyboard, then replug it.
5. Windows will restore the default driver automatically.

## Project Layout

```
app/
  protocol.py        # Pure: blit packet builder, key event parser
  renderer.py        # Pure: PIL -> RGB565, dirty-rect diffing
  profiles.py        # Profile schema validation and management
  actions.py         # Execute action dicts (launch, keys, media, profile)
  usb_link.py        # USB transport: find/claim/reconnect
  sdk_backend.py     # Windows SDK display bridge for touchpad + LCD keys
  input_listener.py  # Read key events, dispatch callbacks
  widgets.py         # Screen widgets (clock, CPU/RAM, now-playing)
  auto_switch.py     # Auto profile switch by foreground app
  daemon.py          # Main loop, state machine
  cli.py             # CLI entry point
  webui/             # Flask web UI
profiles/
  profiles.json      # Configuration
  images/            # User images
tools/               # Diagnostic scripts (enumerate, blit test, listen)
tests/               # pytest test suite
```

## Development

```bash
pip install -r requirements.txt
pip install pytest
python -m pytest tests/ -v
```

## Documentation

- `IMPLEMENTATION_PLAN.md` — Step-by-step guide for driver binding, fixes, and hardware bring-up
- `HANDOFF.md` — Build history, what works, what's blocked, next steps
- `RESEARCH.md` — Protocol dossier and evidence
- `BUILD_SPEC.md` — Implementation specification
- `PLAN.md` — Strategy and rationale
- `PROTOCOL.md` — Wire protocol documentation

## License

MIT License. See [LICENSE](LICENSE) for details.

This project is a clean-room implementation. The wire protocol is derived from
public sources and real hardware captures — no GPL code is included.
