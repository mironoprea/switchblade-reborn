# WinUSB setup and rollback

The display interface `MI_03` must use WinUSB. Interfaces `MI_00`, `MI_01`, and
`MI_02` are keyboard HID interfaces and must never be changed.

## Setup

1. Download Zadig from its official site and run it as Administrator.
2. Select **Options → List All Devices**.
3. Select **Razer DeathStalker Ultimate (Interface 3)** and verify its hardware
   identity contains `VID_1532&PID_0114&MI_03`.
4. Choose **WinUSB** and select **Replace Driver**.
5. Run `python tools\enumerate.py` or restart Switchblade Reborn.

Stop if the selected row does not explicitly identify Interface 3. Changing a
HID interface can temporarily disable keyboard input.

## Rollback

1. Open Device Manager.
2. Find the Interface 3 device under **Universal Serial Bus devices**.
3. Uninstall that device and select driver removal if Windows offers it.
4. Unplug and reconnect the keyboard.

Windows will rediscover the device. No application uninstall step modifies
drivers automatically.
