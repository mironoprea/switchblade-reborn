#!/usr/bin/env python3
"""Analyze USBPcap captures for Switchblade blit headers.

This helper uses tshark to extract USB payload bytes, then looks for the
12-byte rzswitchblade-style blit header:

    opcode, x1, y1, x2, y2, checksum = big-endian uint16 values

Run after recording a Synapse/SDK capture:

    python tools/analyze_capture.py captures/02-set-key-image.pcapng
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


HEADER_SIZE = 12
OP_BLIT = 0x0001
DEFAULT_TSHARK = r"C:\Program Files\Wireshark\tshark.exe"


@dataclass(frozen=True)
class UsbPayload:
    frame: str
    device: str
    endpoint: str
    transfer_type: str
    data: bytes


@dataclass(frozen=True)
class BlitHeader:
    frame: str
    device: str
    endpoint: str
    opcode: int
    x1: int
    y1: int
    x2: int
    y2: int
    checksum: int
    payload_len: Optional[int] = None

    @property
    def width(self) -> int:
        return self.x2 - self.x1 + 1

    @property
    def height(self) -> int:
        return self.y2 - self.y1 + 1

    @property
    def expected_payload_len(self) -> int:
        return self.width * self.height * 2


def parse_capdata(value: str) -> bytes:
    """Parse tshark's colon-separated usb.capdata field."""
    cleaned = value.replace(":", "").replace(" ", "").strip()
    if not cleaned:
        return b""
    return bytes.fromhex(cleaned)


def decode_blit_header(data: bytes) -> Optional[tuple[int, int, int, int, int, int]]:
    if len(data) < HEADER_SIZE:
        return None
    opcode, x1, y1, x2, y2, checksum = struct.unpack(">HHHHHH", data[:HEADER_SIZE])
    if opcode != OP_BLIT:
        return None
    expected = (opcode ^ x1 ^ y1 ^ x2 ^ y2) & 0xFFFF
    if checksum != expected:
        return None
    if x2 < x1 or y2 < y1:
        return None
    return opcode, x1, y1, x2, y2, checksum


def find_blit_headers(payloads: Iterable[UsbPayload]) -> list[BlitHeader]:
    headers: list[BlitHeader] = []
    previous: Optional[BlitHeader] = None
    for payload in payloads:
        decoded = decode_blit_header(payload.data)
        if decoded is not None:
            previous = BlitHeader(
                frame=payload.frame,
                device=payload.device,
                endpoint=payload.endpoint,
                opcode=decoded[0],
                x1=decoded[1],
                y1=decoded[2],
                x2=decoded[3],
                y2=decoded[4],
                checksum=decoded[5],
            )
            headers.append(previous)
            continue

        if previous is not None and previous.payload_len is None and payload.data:
            headers[-1] = BlitHeader(
                frame=previous.frame,
                device=previous.device,
                endpoint=previous.endpoint,
                opcode=previous.opcode,
                x1=previous.x1,
                y1=previous.y1,
                x2=previous.x2,
                y2=previous.y2,
                checksum=previous.checksum,
                payload_len=len(payload.data),
            )
            previous = headers[-1]
    return headers


def _resolve_tshark(path: Optional[str]) -> str:
    if path:
        return path
    found = shutil.which("tshark")
    if found:
        return found
    return DEFAULT_TSHARK


def extract_payloads(capture: Path, *, tshark: Optional[str] = None) -> list[UsbPayload]:
    exe = _resolve_tshark(tshark)
    cmd = [
        exe,
        "-r",
        str(capture),
        "-T",
        "fields",
        "-E",
        "separator=|",
        "-e",
        "frame.number",
        "-e",
        "usb.device_address",
        "-e",
        "usb.endpoint_address",
        "-e",
        "usb.transfer_type",
        "-e",
        "usb.capdata",
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payloads: list[UsbPayload] = []
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[4]:
            continue
        try:
            data = parse_capdata(parts[4])
        except ValueError:
            continue
        payloads.append(
            UsbPayload(
                frame=parts[0],
                device=parts[1],
                endpoint=parts[2],
                transfer_type=parts[3],
                data=data,
            )
        )
    return payloads


def _classify(header: BlitHeader) -> str:
    if header.width == 800 and header.height == 480 and header.x1 == 0 and header.y1 == 0:
        return "screen"
    if header.width in (115, 116) and header.height in (115, 116):
        return "key-sized"
    return "other"


def print_summary(headers: list[BlitHeader]) -> None:
    if not headers:
        print("No valid Switchblade blit headers found.")
        return

    print(f"Found {len(headers)} valid Switchblade blit header(s):")
    for h in headers:
        payload = (
            f"{h.payload_len} bytes"
            if h.payload_len is not None
            else "next payload not captured"
        )
        payload_note = (
            "OK" if h.payload_len == h.expected_payload_len else
            f"expected {h.expected_payload_len}"
        )
        print(
            f"frame {h.frame:>6} dev {h.device:>3} ep {h.endpoint:>4} "
            f"{_classify(h):>9} rect=({h.x1},{h.y1})-({h.x2},{h.y2}) "
            f"{h.width}x{h.height} payload={payload} {payload_note}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="USBPcap .pcap/.pcapng capture")
    parser.add_argument("--tshark", help="Path to tshark.exe")
    args = parser.parse_args()

    if not args.capture.is_file():
        print(f"Error: capture not found: {args.capture}", file=sys.stderr)
        return 1

    try:
        payloads = extract_payloads(args.capture, tshark=args.tshark)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Error running tshark: {exc}", file=sys.stderr)
        return 1

    print_summary(find_blit_headers(payloads))
    return 0


if __name__ == "__main__":
    sys.exit(main())
