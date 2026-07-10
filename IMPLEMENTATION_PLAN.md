# Implementation plan

This is the living completion checklist for the single Switchblade Reborn
product. Historical experiments and the separate compatibility utility are not
part of this repository.

## Completed

- [x] Confirm the composite-device topology and protect HID interfaces.
- [x] Implement direct WinUSB screen blits on endpoint `0x01`.
- [x] Implement direct adaptive-key blits on endpoint `0x02`.
- [x] Decode all ten adaptive-key HID press and release reports.
- [x] Implement profiles, actions, widgets, automatic switching, and web UI.
- [x] Implement reconnect handling and serialized rendering.
- [x] Add per-user paths, tray lifecycle, single-instance handling, autostart,
      rotating logs, and safe profile bootstrapping.
- [x] Replace the external brightness bridge with native HID feature reports.
- [x] Remove the compatibility product and proprietary-runtime backend.
- [x] Add repeatable PyInstaller and Inno Setup packaging.
- [x] Add source, packaging, and release CI.
- [x] Consolidate user, developer, driver, protocol, and troubleshooting docs.

## Release gates

- [ ] On hardware, visually confirm a full-screen image over direct WinUSB.
- [ ] On hardware, visually confirm distinct images on keys 0 through 9.
- [ ] Press and release all ten keys and confirm the configured actions fire once.
- [ ] Confirm both brightness channels at 0%, 50%, and 100%.
- [ ] Unplug and reconnect the keyboard; confirm restoration within five seconds.
- [ ] Reboot with autostart enabled and confirm unattended recovery.
- [ ] Install, upgrade, and uninstall on a clean Windows user account.
- [ ] Sign the executable and installer when a publisher certificate is available.

## Definition of done

The release is done when the gates above pass with the packaged installer, all
automated tests are green, the generated installer can be reproduced from a
clean checkout, and `master` is the repository's only branch.
