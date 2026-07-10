# Troubleshooting

## Device remains disconnected

Run `tools\enumerate.py`. The vendor interface must be interface 3 with bulk OUT
endpoints `0x01` and `0x02`. If Windows denies access, repeat the WinUSB setup
and verify that only `MI_03` changed.

## Display works but keys do not react

Run `tools\listen_hid.py` and press every adaptive key. Reports should begin
with `04 50` through `04 59`, followed by `04 00` on release. Do not rebind a
HID interface.

## Control panel does not open

Open `http://127.0.0.1:8377` manually and inspect:

```text
%LOCALAPPDATA%\SwitchbladeReborn\logs\switchblade-reborn.log
```

## Configuration error

Run `switchblade validate`. Restore a known-good `profiles.json` or remove it to
allow the packaged defaults to be copied on the next launch.
