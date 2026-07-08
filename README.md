# Switchblade Reborn

Standalone Windows control app for the Razer DeathStalker Ultimate Switchblade UI
(4" 800×480 touch LCD + 10 LCD dynamic keys) — replaces discontinued Razer Synapse 2.0.

No Razer login, no cloud, no Synapse process required.

## Quick Start

```powershell
# Create a virtual environment and install dependencies
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Validate your profiles
python -m app.cli validate

# Start the daemon (screen + keys + web UI)
python -m app.cli run
```

The web UI is available at `http://127.0.0.1:8377`.

## CLI Commands

```
python -m app.cli run                 # Start the daemon (screen, keys, web UI)
python -m app.cli profile <name>      # Switch active profile
python -m app.cli blit-screen <image>  # Blit an image to the trackpad screen
python -m app.cli blit-key <N> <img>   # Blit an image to dynamic key N (0-9)
python -m app.cli validate            # Validate profiles.json
python -m app.cli status              # Show connection state and active profile
python -m app.cli install-autostart    # Install Windows Task Scheduler autostart
python -m app.cli uninstall-autostart  # Remove the autostart entry
```

## Features

- **Trackpad screen**: display any image on the 800×480 LCD via the USB blit protocol.
- **Dynamic keys**: display per-key images on all 10 LCD keys.
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

The Switchblade vendor interface must be bound to WinUSB so pyusb can access it.

1. Download [Zadig](https://zadig.akeo.ie/).
2. Options → List All Devices.
3. Find the **Razer DeathStalker Ultimate** entry whose interface is the
   vendor-specific one (class 0xFF, NOT the HID keyboard interfaces).
4. Set the driver to **WinUSB** and click Replace Driver.
5. Only bind the vendor interface — **never** touch HID interfaces (class 0x03).

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

- `RESEARCH.md` — Protocol dossier and evidence
- `BUILD_SPEC.md` — Implementation specification
- `PLAN.md` — Strategy and rationale
- `PROTOCOL.md` — Wire protocol documentation

## License

MIT License. See [LICENSE](LICENSE) for details.

This project is a clean-room implementation. The wire protocol is derived from
public sources and real hardware captures — no GPL code is included.
