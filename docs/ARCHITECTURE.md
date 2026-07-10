# Architecture

Switchblade Reborn is one process with four boundaries:

1. `usb_link.py`, `protocol.py`, `renderer.py`, and `input_listener.py` own the
   hardware boundary. Protocol and rendering are pure and unit-tested.
2. `daemon.py` owns connection state, rendering, actions, and hotplug recovery.
3. `profiles.py`, `actions.py`, `widgets.py`, and `auto_switch.py` own product
   behavior without depending on the web UI.
4. `desktop.py` and `webui/` own the Windows lifecycle and local control panel.

The web server binds only to `127.0.0.1`, validates the Host header, re-encodes
uploaded images, and applies validated profile updates atomically. Installed
builds treat bundled profiles as read-only defaults and copy them to a writable
per-user directory on first launch.

Hardware failures transition the transport back to `DISCONNECTED`; the daemon
polls until the device returns, then performs a full redraw. HID input remains
separate from WinUSB display traffic, so the ordinary keyboard interfaces are
never claimed or rebound by the application.
