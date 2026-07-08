#!/usr/bin/env python3
"""Enumerate all USB interfaces and endpoints for the DeathStalker Ultimate.

Usage: python tools/enumerate.py
"""

import sys
import usb.core
import usb.util

VID = 0x1532
PID = 0x0114


def main() -> int:
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print(f"No device found for VID=0x{VID:04x} PID=0x{PID:04x}")
        return 1

    print(f"Device: VID=0x{VID:04x} PID=0x{PID:04x}")
    print(f"  Manufacturer: {usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else 'N/A'}")
    print(f"  Product: {usb.util.get_string(dev, dev.iProduct) if dev.iProduct else 'N/A'}")
    print()

    cfg = dev.get_active_configuration()
    print(f"Configuration {cfg.bConfigurationValue}:")
    print()

    for iface in cfg:
        cls = iface.bInterfaceClass
        cls_name = {
            0x03: "HID",
            0xFF: "Vendor-specific",
        }.get(cls, f"0x{cls:02x}")

        print(f"  Interface {iface.bInterfaceNumber}: class={cls_name} (0x{cls:02x})")
        print(f"    subclass=0x{iface.bInterfaceSubClass:02x} protocol=0x{iface.bInterfaceProtocol:02x}")

        for ep in iface:
            addr = ep.bEndpointAddress
            direction = "IN" if addr & 0x80 else "OUT"
            ep_type = {0: "control", 1: "iso", 2: "bulk", 3: "interrupt"}.get(
                ep.bmAttributes, f"unknown({ep.bmAttributes})"
            )
            print(f"    Endpoint 0x{addr:02x} ({direction}, {ep_type}, max_pkt={ep.wMaxPacketSize})")

        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
