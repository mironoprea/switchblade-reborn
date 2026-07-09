"""
Screen widgets for Phase 4: clock, CPU/RAM, now-playing.

Widgets render onto a base image and are re-drawn at 1 Hz through the
existing dirty-rect renderer.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .protocol import SCREEN_WIDTH, SCREEN_HEIGHT

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _get_font(size: int = 20) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to find a usable font; fall back to default.

    Cached per size — the font file was previously re-read on every widget
    render (once a second).
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_clock(
    img: Image.Image,
    x: int,
    y: int,
    *,
    font_size: int = 28,
) -> tuple[int, int, int, int]:
    """Draw a clock on *img*.  Returns the dirty rect (x1, y1, x2, y2)."""
    draw = ImageDraw.Draw(img)
    font = _get_font(font_size)
    text = datetime.now().strftime("%H:%M:%S")
    bbox = draw.textbbox((x, y), text, font=font)
    # Clear the area first
    draw.rectangle([bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2], fill=(0, 0, 0))
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return (bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2)


def render_cpu_ram(
    img: Image.Image,
    x: int,
    y: int,
    *,
    font_size: int = 18,
) -> tuple[int, int, int, int]:
    """Draw CPU% and RAM% on *img*.  Returns dirty rect."""
    draw = ImageDraw.Draw(img)
    font = _get_font(font_size)

    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
    except ImportError:
        cpu = 0.0
        ram = 0.0

    text = f"CPU {cpu:.0f}%  RAM {ram:.0f}%"
    bbox = draw.textbbox((x, y), text, font=font)
    draw.rectangle([bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2], fill=(0, 0, 0))
    draw.text((x, y), text, fill=(100, 255, 100), font=font)
    return (bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2)


def render_now_playing(
    img: Image.Image,
    x: int,
    y: int,
    *,
    font_size: int = 16,
) -> tuple[int, int, int, int]:
    """Draw 'now playing' track info.  Returns dirty rect."""
    draw = ImageDraw.Draw(img)
    font = _get_font(font_size)

    title, artist = _get_now_playing()
    line1 = f"♪ {title}" if title else "♪ (nothing playing)"
    line2 = artist if artist else ""

    bbox1 = draw.textbbox((x, y), line1, font=font)
    bbox2 = draw.textbbox((x, y + font_size + 2), line2, font=font) if line2 else bbox1

    x1 = min(bbox1[0], bbox2[0]) - 2
    y1 = bbox1[1] - 2
    x2 = max(bbox1[2], bbox2[2]) + 2
    y2 = (bbox2[3] if line2 else bbox1[3]) + 2

    draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0))
    draw.text((x, y), line1, fill=(200, 200, 255), font=font)
    if line2:
        draw.text((x, y + font_size + 2), line2, fill=(180, 180, 180), font=font)

    return (x1, y1, x2, y2)


def _get_now_playing() -> tuple[str, str]:
    """Return (title, artist) of the currently playing track."""
    try:
        if os.name == "nt":
            return _get_now_playing_windows()
    except Exception as exc:
        logger.debug("Now-playing error: %s", exc)
    return ("", "")


def _get_now_playing_windows() -> tuple[str, str]:
    """Windows-only now-playing via GSMTC (winsdk/winrt)."""
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )
    except ImportError:
        return ("", "")

    try:
        import asyncio

        async def _get():
            manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
            session = manager.get_current_session()
            if session is None:
                return ("", "")
            info = await session.try_get_media_properties_async()
            return (info.title, info.artist)

        return asyncio.run(_get())
    except Exception as exc:
        logger.debug("Now-playing (Windows) error: %s", exc)
        return ("", "")


# ---------------------------------------------------------------------------
# Widget board rendering
# ---------------------------------------------------------------------------

def render_widget_board(
    screen_config: dict,
    base_image: Optional[Image.Image] = None,
) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
    """Render a widget_board screen config onto an image.

    Returns (image, dirty_rects).
    """
    if base_image is None:
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (10, 10, 10))
    else:
        img = base_image.copy()

    dirty_rects: list[tuple[int, int, int, int]] = []
    for widget in screen_config.get("widgets", []):
        wtype = widget.get("type")
        x = widget.get("x", 10)
        y = widget.get("y", 10)
        if wtype == "clock":
            rect = render_clock(img, x, y, font_size=widget.get("font_size", 28))
        elif wtype == "cpu_ram":
            rect = render_cpu_ram(img, x, y, font_size=widget.get("font_size", 18))
        elif wtype == "media_now_playing":
            rect = render_now_playing(img, x, y, font_size=widget.get("font_size", 16))
        else:
            continue
        dirty_rects.append(rect)

    return img, dirty_rects
