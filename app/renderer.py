"""
Pure rendering functions: PIL image -> RGB565 bytes and dirty-rect diffing.

No USB, no globals — unit-testable without hardware.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image

from .protocol import SCREEN_WIDTH, SCREEN_HEIGHT, KEY_IMAGE_SIZE


# ---------------------------------------------------------------------------
# RGB565 conversion
# ---------------------------------------------------------------------------

def image_to_rgb565(
    img: Image.Image,
    *,
    endian: str = "little",
) -> bytes:
    """Convert a PIL image to RGB565 byte stream.

    *endian* is ``'big'`` or ``'little'`` — the byte order within each 16-bit
    pixel word.  Little-endian is the hardware-confirmed default.
    """
    if endian not in ("big", "little"):
        raise ValueError(f"endian must be 'big' or 'little', got {endian!r}")

    img = img.convert("RGB")
    px = img.load()
    w, h = img.size
    fmt = ">H" if endian == "big" else "<H"
    buf = bytearray(w * h * 2)
    pos = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            # RGB565: 5 red, 6 green, 5 blue
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            struct.pack_into(fmt, buf, pos, val)
            pos += 2
    return bytes(buf)


def image_to_rgb565_fast(img: Image.Image, *, endian: str = "little") -> bytes:
    """Optimized RGB565 using numpy bit operations."""
    if endian not in ("big", "little"):
        raise ValueError(f"endian must be 'big' or 'little', got {endian!r}")

    import numpy as np

    img = img.convert("RGB")
    arr = np.asarray(img, dtype=np.uint8)
    r5 = (arr[:, :, 0].astype(np.uint16) >> 3) & 0x1F
    g6 = (arr[:, :, 1].astype(np.uint16) >> 2) & 0x3F
    b5 = (arr[:, :, 2].astype(np.uint16) >> 3) & 0x1F
    val = (r5 << 11) | (g6 << 5) | b5  # uint16 array
    # Determine byte order
    if endian == "big":
        return val.byteswap(False).tobytes()
    else:
        return val.tobytes()


def load_image(path: str) -> Image.Image:
    """Load an image file, returning a PIL Image."""
    return Image.open(path)


def resize_to_screen(img: Image.Image) -> Image.Image:
    """Resize an image to exactly 800×480."""
    return img.resize((SCREEN_WIDTH, SCREEN_HEIGHT), Image.LANCZOS)


def resize_to_key(img: Image.Image) -> Image.Image:
    """Resize an image to exactly the key image size."""
    return img.resize((KEY_IMAGE_SIZE, KEY_IMAGE_SIZE), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Dirty-rect diffing
# ---------------------------------------------------------------------------

@dataclass
class DirtyRect:
    """A rectangular region that changed between two framebuffers."""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1 + 1

    @property
    def height(self) -> int:
        return self.y2 - self.y1 + 1

    def is_empty(self) -> bool:
        return self.width < 0 or self.height < 0


def compute_dirty_rect(
    current: Optional[bytes],
    pending: bytes,
    width: int,
    height: int,
    *,
    threshold: int = 0,
) -> Optional[DirtyRect]:
    """Compute the bounding rectangle of changed pixels.

    ``current`` may be ``None`` (forces a full redraw).
    ``threshold`` is the per-channel difference below which pixels are
    considered unchanged (0 = exact match only).

    Returns ``None`` if nothing changed (and current is not None).
    """
    if current is None:
        return DirtyRect(0, 0, width - 1, height - 1)

    if len(current) != len(pending):
        return DirtyRect(0, 0, width - 1, height - 1)

    import numpy as np

    cur = np.frombuffer(current, dtype=np.uint8).reshape((height, width, -1))
    pen = np.frombuffer(pending, dtype=np.uint8).reshape((height, width, -1))

    if threshold > 0:
        diff = np.abs(cur.astype(np.int16) - pen.astype(np.int16))
        mask = np.any(diff > threshold, axis=-1)
    else:
        mask = np.any(cur != pen, axis=-1)

    if not mask.any():
        return None

    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    y1, y2 = int(np.argmax(rows)), int(len(rows) - 1 - np.argmax(rows[::-1]))
    x1, x2 = int(np.argmax(cols)), int(len(cols) - 1 - np.argmax(cols[::-1]))
    return DirtyRect(x1, y1, x2, y2)


def extract_region(
    rgb565_bytes: bytes,
    width: int,
    height: int,
    rect: DirtyRect,
    *,
    endian: str = "little",
) -> bytes:
    """Extract a sub-rectangle from a full RGB565 framebuffer.

    Returns just the pixels within *rect*, row by row, as RGB565 bytes.
    """
    import numpy as np

    dtype = np.dtype(">u2") if endian == "big" else np.dtype("<u2")
    fb = np.frombuffer(rgb565_bytes, dtype=dtype).reshape((height, width))
    region = fb[rect.y1:rect.y2 + 1, rect.x1:rect.x2 + 1]
    return region.tobytes()


# ---------------------------------------------------------------------------
# Renderer state
# ---------------------------------------------------------------------------

@dataclass
class ScreenRenderer:
    """Manages current/pending framebuffers and dirty-rect blitting."""
    width: int = SCREEN_WIDTH
    height: int = SCREEN_HEIGHT
    endian: str = "little"
    _current: Optional[bytes] = field(default=None, repr=False)
    _pending: Optional[bytes] = field(default=None, repr=False)

    @property
    def current(self) -> Optional[bytes]:
        return self._current

    @property
    def pending(self) -> Optional[bytes]:
        return self._pending

    def update(self, rgb565_bytes: bytes) -> Optional[tuple[DirtyRect, bytes]]:
        """Set the pending framebuffer and return (dirty_rect, payload) if changed.

        The payload is just the changed pixels (RGB565), not a full frame.
        Returns ``None`` if nothing changed.
        """
        if len(rgb565_bytes) != self.width * self.height * 2:
            raise ValueError(
                f"framebuffer must be {self.width * self.height * 2} bytes, "
                f"got {len(rgb565_bytes)}"
            )

        self._pending = rgb565_bytes
        rect = compute_dirty_rect(self._current, self._pending, self.width, self.height)
        if rect is None or rect.is_empty():
            self._current = self._pending
            return None

        payload = extract_region(
            self._pending, self.width, self.height, rect, endian=self.endian
        )
        self._current = self._pending
        return rect, payload

    def force_full_redraw(self) -> Optional[tuple[DirtyRect, bytes]]:
        """Force a full-screen blit on next update by clearing current."""
        self._current = None
        return None


def render_image_to_framebuffer(
    path: str,
    *,
    width: int = SCREEN_WIDTH,
    height: int = SCREEN_HEIGHT,
    endian: str = "little",
) -> bytes:
    """Load, resize, and convert an image file to an RGB565 framebuffer."""
    img = load_image(path)
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    return image_to_rgb565_fast(img, endian=endian)


def render_key_image_to_rgb565(
    path: str,
    *,
    endian: str = "little",
) -> bytes:
    """Load, resize, and convert a key image to RGB565."""
    img = load_image(path)
    img = resize_to_key(img)
    return image_to_rgb565_fast(img, endian=endian)


def render_solid_color(
    r: int,
    g: int,
    b: int,
    *,
    width: int = SCREEN_WIDTH,
    height: int = SCREEN_HEIGHT,
    endian: str = "little",
) -> bytes:
    """Generate a solid-color RGB565 framebuffer (for testing)."""
    img = Image.new("RGB", (width, height), (r, g, b))
    return image_to_rgb565_fast(img, endian=endian)
