# Switchblade Hardware Handoff Reference

## Current Verified State

- Branch: `codex/hardware-capture-handoff`.
- Hardware: Razer DeathStalker Ultimate, VID `1532`, PID `0114`.
- MI_03 currently uses the original Razer driver (`Razer DeathStalker Ultimate`, driver `oem16.inf` in prior checks), which is correct for the SDK backend.
- Physical key input is HID, not vendor bulk IN. Reports are `04 50` through `04 59` for key down and `04 00` for release.
- USBPcap is installed but not useful on this host: only `\\.\USBPcap1` opens and captures no keyboard traffic; roots 2-8 fail.
- A Frida trace of `SdkExerciser.exe` recovered the direct physical-key image path.

## Display Paths

Use the SDK path first:

```powershell
python -m app.cli run --backend sdk --no-web
python -m app.cli blit-key 0 profiles\images\key0.png --backend sdk
```

Expected daemon log:

```text
Display backend: Razer SwitchBlade SDK.
Device ready. Rendering active profile.
HID key listener opened 4 collections.
```

The SDK backend builds `SwitchbladeSdkBridge.exe` under `%LOCALAPPDATA%\SwitchbladeReborn\sdk-bridge`.
It is x86 because `RzSwitchbladeSDK2.dll` is 32-bit.

Use the direct USB path only after MI_03 is rebound to WinUSB:

```powershell
python -m app.cli run --backend usb
```

Direct USB uses bulk OUT `0x01` for the main 800x480 LCD and bulk OUT `0x02` for
physical LCD keys when that endpoint is present.

## Visual Verification

ADB path on this machine:

```powershell
C:\Users\miron\AppData\Local\Android\Sdk\platform-tools\adb.exe
```

Take a proof photo:

```powershell
python tools\adb_photo.py --adb "C:\Users\miron\AppData\Local\Android\Sdk\platform-tools\adb.exe" --output captures\phone\keyboard.jpg --settle-seconds 2
```

Known proof artifacts from 2026-07-09:

- `captures\phone\sdk-backend-key0.jpg`: `blit-key 0 --backend sdk` updated the physical key.
- `captures\phone\sdk-backend-full-profile.jpg`: daemon rendered all ten key images and the main LCD.

## Remaining Gaps

- Direct USB physical key-image protocol is implemented from SDK client trace:
  device path suffix `\2`, bulk OUT `0x02`, 12-byte blit header plus 26,450-byte
  115x115 RGB565 payload.
- The remaining direct-USB task is visual verification after MI_03 is rebound to WinUSB.
- Brightness command is still unknown.
- USB reference capture remains blocked by USBPcap root visibility on this machine.

## Required Checks Before Handoff

```powershell
pytest
python -m compileall app tools tests
git diff --check
```

Expected test baseline: `157 passed`.
