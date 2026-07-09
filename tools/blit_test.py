#!/usr/bin/env python3
"""Send a test image to the trackpad screen.

Usage: python tools/blit_test.py <image_path> [--endian big|little]
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.usb_link import UsbLink
from app import protocol
from app.renderer import render_image_to_framebuffer


def main() -> int:
    parser = argparse.ArgumentParser(description="Blit a test image to the trackpad screen")
    parser.add_argument("image", help="Path to image file")
    parser.add_argument("--endian", choices=["big", "little"], default="little")
    parser.add_argument("--interface", type=int, default=None)
    args = parser.parse_args()

    if not os.path.isfile(args.image):
        print(f"Error: {args.image} not found", file=sys.stderr)
        return 1

    link = UsbLink(interface=args.interface)
    print("Looking for device...")
    for _ in range(10):
        link.poll()
        if link.state in ("READY", "INITIALIZING"):
            break
    if not link.is_ready() and link.state != "INITIALIZING":
        print(f"Error: device state is {link.state}", file=sys.stderr)
        return 1

    link.mark_ready()
    print(f"Sending blit: {args.image} (endian={args.endian})")

    fb = render_image_to_framebuffer(args.image, endian=args.endian)
    packet = protocol.build_screen_blit(fb)
    link.write_transfer(packet[:protocol.HEADER_SIZE])
    link.write_transfer(packet[protocol.HEADER_SIZE:])
    print("Blit sent.")
    link.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
