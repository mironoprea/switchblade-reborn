#!/usr/bin/env python3
"""Listen for raw HID reports from DeathStalker Ultimate collections.

Usage:
    python tools/listen_hid.py
    python tools/listen_hid.py --include-keyboard --seconds 30
"""

from __future__ import annotations

import argparse
import sys
import time

import hid

VID = 0x1532
PID = 0x0114
READ_SIZE = 64


def _is_keyboard_collection(device_info: dict) -> bool:
    return device_info.get("usage_page") == 0x01 and device_info.get("usage") == 0x06


def _label(device_info: dict) -> str:
    interface = device_info.get("interface_number")
    usage_page = device_info.get("usage_page")
    usage = device_info.get("usage")
    path = device_info.get("path")
    if isinstance(path, bytes):
        path = path.decode(errors="replace")
    return (
        f"interface={interface} "
        f"usage_page=0x{usage_page or 0:04x} "
        f"usage=0x{usage or 0:04x} "
        f"path={path}"
    )


def _open_devices(include_keyboard: bool):
    handles = []
    for index, info in enumerate(hid.enumerate(VID, PID)):
        if _is_keyboard_collection(info) and not include_keyboard:
            print(f"[{index}] skip keyboard collection: {_label(info)}")
            continue

        dev = hid.device()
        try:
            dev.open_path(info["path"])
            dev.set_nonblocking(True)
        except OSError as exc:
            print(f"[{index}] open failed: {exc}; {_label(info)}", file=sys.stderr)
            continue

        print(f"[{index}] listening: {_label(info)}")
        handles.append((index, info, dev))
    return handles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-keyboard",
        action="store_true",
        help="also open standard keyboard HID collections",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="stop after this many seconds; default runs until Ctrl+C",
    )
    args = parser.parse_args()

    handles = _open_devices(args.include_keyboard)
    if not handles:
        print("No readable DeathStalker HID collections found.", file=sys.stderr)
        return 1

    print("Press LCD keys now. Raw HID reports will be printed as hex.")
    started = time.monotonic()
    try:
        while True:
            if args.seconds and time.monotonic() - started >= args.seconds:
                break

            any_data = False
            for index, _info, dev in handles:
                data = bytes(dev.read(READ_SIZE))
                if data:
                    any_data = True
                    print(f"[{index}] RAW: {data.hex()}")

            if not any_data:
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        for _index, _info, dev in handles:
            dev.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
