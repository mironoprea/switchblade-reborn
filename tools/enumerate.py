#!/usr/bin/env python3
"""Enumerate all USB interfaces and endpoints for the DeathStalker Ultimate.

Usage: python tools/enumerate.py
"""

import sys
import usb.core
import usb.util

try:
    import libusb_package
    _BACKEND = libusb_package.get_libusb1_backend()
except Exception:
    _BACKEND = None

VID = 0x1532
PID = 0x0114


def _safe_get_string(dev, index: int) -> str:
    if not index:
        return "N/A"

    try:
        value = usb.util.get_string(dev, index)
    except (ValueError, usb.core.USBError) as exc:
        return f"<unavailable: {exc}>"

    return value or "N/A"


def main() -> int:
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=_BACKEND)
    if dev is None:
        print(f"No device found for VID=0x{VID:04x} PID=0x{PID:04x}")
        return 1

    print(f"Device: VID=0x{VID:04x} PID=0x{PID:04x}")
    print(f"  Manufacturer: {_safe_get_string(dev, dev.iManufacturer)}")
    print(f"  Product: {_safe_get_string(dev, dev.iProduct)}")
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

        alt = getattr(iface, "bAlternateSetting", 0)
        alt_text = f" alt={alt}" if alt else ""
        print(f"  Interface {iface.bInterfaceNumber}{alt_text}: class={cls_name} (0x{cls:02x})")
        print(f"    subclass=0x{iface.bInterfaceSubClass:02x} protocol=0x{iface.bInterfaceProtocol:02x}")

        for ep in iface:
            addr = ep.bEndpointAddress
            direction = "IN" if addr & 0x80 else "OUT"
            transfer_type = ep.bmAttributes & 0x03
            ep_type = {0: "control", 1: "iso", 2: "bulk", 3: "interrupt"}.get(
                transfer_type, f"unknown({ep.bmAttributes})"
            )
            print(f"    Endpoint 0x{addr:02x} ({direction}, {ep_type}, max_pkt={ep.wMaxPacketSize})")

        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
