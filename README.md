# Switchblade Reborn

Switchblade Reborn is a local Windows control application for the Razer
DeathStalker Ultimate's 800×480 touch display and ten adaptive LCD keys. It uses
the keyboard directly through WinUSB and HID; no account, cloud service, vendor
control process, or proprietary runtime is required.

## Features

- Images and live widgets on the 800×480 display.
- A separate image and action for each adaptive key.
- Launch, shortcut, media, and profile-switch actions.
- Automatic profiles based on the foreground application.
- Native HID brightness control for the keyboard and adaptive keys.
- Local web control panel at `http://127.0.0.1:8377`.
- Tray lifecycle, single-instance protection, rotating logs, autostart, and
  hotplug recovery.

## Install

Release builds produce `Switchblade Reborn Setup.exe`. Run the installer, then
complete the one-time WinUSB setup in [docs/DRIVER_SETUP.md](docs/DRIVER_SETUP.md).
The driver operation must target only `MI_03`; the three HID interfaces must
remain unchanged.

Launch **Switchblade Reborn** from the Start Menu. The control panel opens in the
default browser and the tray icon keeps the hardware service running.

User profiles, images, and logs are stored under:

```text
%LOCALAPPDATA%\SwitchbladeReborn
```

Uninstalling the app leaves user profiles in place so upgrades are safe.

## Source setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,build]"
python -m pytest -q
python -m app.cli validate
python -m app.desktop
```

Useful commands:

```powershell
python -m app.cli run
python -m app.cli profile default
python -m app.cli blit-screen profiles\images\bg.png
python -m app.cli blit-key 0 profiles\images\key0.png
python -m app.cli brightness 80
python -m app.cli brightness 80 --target keyboard
python tools\enumerate.py
python tools\listen_hid.py
```

## Configuration

Profiles live in `profiles.json`. Each profile contains one screen definition
and exactly ten key entries. The control panel edits the same file atomically.

```json
{
  "version": 1,
  "active_profile": "default",
  "settings": { "brightness": 80, "fps_cap": 15 },
  "auto_switch": { "code.exe": "coding" },
  "profiles": {
    "default": {
      "screen": { "type": "image", "path": "images/bg.png" },
      "keys": [
        {
          "image": "images/key0.png",
          "label": "Editor",
          "action": { "type": "launch", "path": "C:/Windows/notepad.exe" }
        }
      ]
    }
  }
}
```

The real file must contain ten key entries. Supported actions are `launch`,
`keys`, `media`, and `profile`; supported screen types are `image` and
`widget_board`.

## Documentation

- [Implementation plan](IMPLEMENTATION_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Hardware protocol](docs/PROTOCOL.md)
- [Driver setup and rollback](docs/DRIVER_SETUP.md)
- [Development and release](docs/DEVELOPMENT.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

Licensed under the [MIT License](LICENSE).
