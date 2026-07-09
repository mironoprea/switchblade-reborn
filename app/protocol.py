"""
Pure protocol functions for the Razer DeathStalker Ultimate Switchblade UI.

No USB, no globals — unit-testable without hardware.

Protocol facts (derived from rzswitchblade C sources and RESEARCH.md):

  * Blit packet = 12-byte header + RGB565 pixel payload.
  * Header = six big-endian uint16: opcode, x1, y1, x2, y2, checksum.
  * Checksum = XOR of the five preceding uint16 values (as uint16).
  * Rect is **inclusive** — pixel count = (x2 - x1 + 1) * (y2 - y1 + 1).
  * Pixel format = RGB565, 2 bytes per pixel, little-endian within each pixel
    word on confirmed hardware.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OP_BLIT = 0x0001

HEADER_SIZE = 12           # 6 × uint16
HEADER_FORMAT = ">HHHHHH"  # big-endian

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480

KEY_COUNT = 10
KEY_IMAGE_SIZE = 115       # official SDK key bitmap size

VENDOR_VID = 0x1532
VENDOR_PID = 0x0114

# Endpoint addresses confirmed on DeathStalker Ultimate interface MI_03.
BULK_OUT_EP = 0x01
BULK_KEY_OUT_EP = 0x02
BULK_IN_EP = 0x02

HID_KEY_REPORT_ID = 0x04
HID_KEY_BASE = 0x50

# Captured from the official SwitchBlade SDK client path.  The SDK opens
# the same device interface with suffix "\2" and writes these blit headers
# followed by a 115x115 RGB565 payload.  The header rectangles are 116x116
# in coordinate space; the device/driver accepts the 115x115 payload.
KEY_RECTS: tuple[tuple[int, int, int, int], ...] = (
    (9, 318, 124, 433),
    (178, 318, 293, 433),
    (346, 318, 461, 433),
    (515, 318, 630, 433),
    (683, 318, 798, 433),
    (9, 151, 124, 266),
    (178, 151, 293, 266),
    (346, 151, 461, 266),
    (515, 151, 630, 266),
    (683, 151, 798, 266),
)


# ---------------------------------------------------------------------------
# Blit packet builder
# ---------------------------------------------------------------------------

def _xor_checksum(opcode: int, x1: int, y1: int, x2: int, y2: int) -> int:
    """XOR of the five uint16 header fields, as a uint16."""
    return (opcode ^ x1 ^ y1 ^ x2 ^ y2) & 0xFFFF


def build_blit(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    rgb565_bytes: bytes,
    *,
    opcode: int = OP_BLIT,
) -> bytes:
    """Build a full blit packet (header + payload) as ``bytes``.

    Coordinates are inclusive.  The caller is responsible for ensuring
    ``len(rgb565_bytes)`` matches ``(x2 - x1 + 1) * (y2 - y1 + 1) * 2``.

    Raises ``ValueError`` on coordinate or payload-size mismatch.
    """
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    if not (0 <= x1 <= 0xFFFF and 0 <= x2 <= 0xFFFF):
        raise ValueError(f"x coordinates out of range: {x1}, {x2}")
    if not (0 <= y1 <= 0xFFFF and 0 <= y2 <= 0xFFFF):
        raise ValueError(f"y coordinates out of range: {y1}, {y2}")

    width = x2 - x1 + 1
    height = y2 - y1 + 1
    expected = width * height * 2
    if len(rgb565_bytes) != expected:
        raise ValueError(
            f"payload size mismatch: expected {expected} bytes "
            f"({width}x{height}x2), got {len(rgb565_bytes)}"
        )

    checksum = _xor_checksum(opcode, x1, y1, x2, y2)
    header = struct.pack(HEADER_FORMAT, opcode, x1, y1, x2, y2, checksum)
    return header + rgb565_bytes


def build_blit_header(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    opcode: int = OP_BLIT,
) -> bytes:
    """Build only the 12-byte blit header."""
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    checksum = _xor_checksum(opcode, x1, y1, x2, y2)
    return struct.pack(HEADER_FORMAT, opcode, x1, y1, x2, y2, checksum)


# ---------------------------------------------------------------------------
# Key blit helper
# ---------------------------------------------------------------------------

def key_rect(key_index: int) -> tuple[int, int, int, int]:
    """Return the captured SDK blit rectangle for a dynamic key."""
    if not 0 <= key_index < KEY_COUNT:
        raise ValueError(f"key index must be 0-{KEY_COUNT - 1}, got {key_index}")
    return KEY_RECTS[key_index]


def build_key_blit(key_index: int, rgb565_bytes: bytes) -> bytes:
    """Build a blit packet for a single dynamic key image."""
    x1, y1, x2, y2 = key_rect(key_index)
    expected = KEY_IMAGE_SIZE * KEY_IMAGE_SIZE * 2
    if len(rgb565_bytes) != expected:
        raise ValueError(
            f"key payload size mismatch: expected {expected} bytes "
            f"({KEY_IMAGE_SIZE}x{KEY_IMAGE_SIZE}x2), got {len(rgb565_bytes)}"
        )
    return build_blit_header(x1, y1, x2, y2) + rgb565_bytes


def build_screen_blit(rgb565_bytes: bytes) -> bytes:
    """Build a full-screen (800×480) blit packet."""
    return build_blit(0, 0, SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, rgb565_bytes)


# ---------------------------------------------------------------------------
# Key event parsing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KeyEvent:
    """A parsed dynamic-key event from the vendor IN endpoint."""
    key_index: int
    pressed: bool
    raw: bytes

    def __str__(self) -> str:
        state = "down" if self.pressed else "up"
        return f"key {self.key_index} {state}"


def parse_key_event(data: bytes) -> Optional[KeyEvent]:
    """Parse a raw IN-endpoint packet into a ``KeyEvent`` or ``None``.

    The exact format is [UNKNOWN] until confirmed by capture.  The seed
    hypothesis (from rzswitchblade endpoint 0x02) is a short packet where
    byte 0 is the key index (1-indexed: 1-10) and byte 1 indicates down/up.

    If the packet doesn't match any known pattern, returns ``None`` so the
    caller can log raw hex for analysis.
    """
    if not data:
        return None

    # Pattern 1: [key_1indexed, down/up_flag, ...]
    #   key index 1-10, flag: nonzero = down, zero = up
    if len(data) >= 2:
        idx = data[0]
        if 1 <= idx <= KEY_COUNT:
            pressed = data[1] != 0
            return KeyEvent(key_index=idx - 1, pressed=pressed, raw=bytes(data))

    # Pattern 2: single-byte bitmask (each bit = one key, down when set).
    # Restricted to length-1 packets: the old `mask < (1 << KEY_COUNT)` bound was
    # always true for a byte (max 255 < 1024), so any unmatched multi-byte junk
    # was misread as a key press.  Returns the lowest set bit.  Note this pattern
    # cannot express key-up.
    if len(data) == 1:
        mask = data[0]
        if mask != 0:
            for i in range(KEY_COUNT):
                if mask & (1 << i):
                    return KeyEvent(key_index=i, pressed=True, raw=bytes(data))

    return None


def parse_hid_key_event(data: bytes, pressed_key: Optional[int] = None) -> Optional[KeyEvent]:
    """Parse a DeathStalker LCD-key HID report.

    Hardware capture confirms non-keyboard HID collection reports shaped like:

    * ``04 50 ...`` through ``04 59 ...`` for key 0 through key 9 down.
    * ``04 00 ...`` for release of the previously pressed key.

    ``pressed_key`` supplies that previous key for release reports.
    """
    if len(data) < 2 or data[0] != HID_KEY_REPORT_ID:
        return None

    code = data[1]
    if HID_KEY_BASE <= code < HID_KEY_BASE + KEY_COUNT:
        return KeyEvent(key_index=code - HID_KEY_BASE, pressed=True, raw=bytes(data))
    if code == 0 and pressed_key is not None:
        return KeyEvent(key_index=pressed_key, pressed=False, raw=bytes(data))
    return None
