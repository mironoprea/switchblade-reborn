#!/usr/bin/env python3
"""Listen for key events on the vendor IN endpoint and print raw hex.

Usage: python tools/listen_keys.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.usb_link import UsbLink
from app.protocol import parse_key_event


def main() -> int:
    link = UsbLink()
    print("Looking for device...")
    for _ in range(10):
        link.poll()
        if link.state in ("READY", "INITIALIZING"):
            break
        time.sleep(0.5)
    if not link.state in ("READY", "INITIALIZING"):
        print(f"Error: device state is {link.state}", file=sys.stderr)
        return 1

    link.mark_ready()
    print("Listening for key events (Ctrl+C to stop)...")
    try:
        while True:
            try:
                data = link.read(length=512, timeout=500)
            except ConnectionError:
                print("Device disconnected.")
                break
            if not data:
                continue
            print(f"RAW: {data.hex()}")
            event = parse_key_event(data)
            if event:
                print(f"  -> {event}")
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        link.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
