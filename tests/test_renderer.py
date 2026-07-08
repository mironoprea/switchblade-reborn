"""Tests for app.renderer — pure functions, no hardware needed."""

import pytest
from PIL import Image
from app import renderer
from app.protocol import SCREEN_WIDTH, SCREEN_HEIGHT, KEY_IMAGE_SIZE


class TestRGB565:
    def test_solid_red(self):
        img = Image.new("RGB", (2, 2), (255, 0, 0))
        data = renderer.image_to_rgb565_fast(img, endian="big")
        assert len(data) == 2 * 2 * 2
        # Red in RGB565 big-endian: r5=31(0x1F)<<11=0xF800
        # As big-endian bytes: 0xF8, 0x00
        assert data[:2] == b"\xF8\x00"

    def test_solid_green(self):
        img = Image.new("RGB", (1, 1), (0, 255, 0))
        data = renderer.image_to_rgb565_fast(img, endian="big")
        # Green in RGB565: g6=63(0x3F)<<5=0x07E0
        # Big-endian: 0x07, 0xE0
        assert data == b"\x07\xE0"

    def test_solid_blue(self):
        img = Image.new("RGB", (1, 1), (0, 0, 255))
        data = renderer.image_to_rgb565_fast(img, endian="big")
        # Blue in RGB565: b5=31(0x1F)=0x001F
        # Big-endian: 0x00, 0x1F
        assert data == b"\x00\x1F"

    def test_black(self):
        img = Image.new("RGB", (1, 1), (0, 0, 0))
        data = renderer.image_to_rgb565_fast(img, endian="big")
        assert data == b"\x00\x00"

    def test_white(self):
        img = Image.new("RGB", (1, 1), (255, 255, 255))
        data = renderer.image_to_rgb565_fast(img, endian="big")
        # RGB565 white: 0xFFFF
        assert data == b"\xFF\xFF"

    def test_endian_swap(self):
        img = Image.new("RGB", (1, 1), (255, 0, 0))
        big = renderer.image_to_rgb565_fast(img, endian="big")
        little = renderer.image_to_rgb565_fast(img, endian="little")
        # Same value, different byte order
        assert big[0] == little[1] and big[1] == little[0]

    def test_size_full_screen(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        data = renderer.image_to_rgb565_fast(img)
        assert len(data) == SCREEN_WIDTH * SCREEN_HEIGHT * 2

    def test_key_image_size(self):
        img = Image.new("RGB", (KEY_IMAGE_SIZE, KEY_IMAGE_SIZE), (128, 128, 128))
        data = renderer.image_to_rgb565_fast(img)
        assert len(data) == KEY_IMAGE_SIZE * KEY_IMAGE_SIZE * 2


class TestDirtyRect:
    def test_full_redraw_on_none(self):
        rect = renderer.compute_dirty_rect(None, b"\x00" * 100, 10, 5)
        assert rect is not None
        assert rect.x1 == 0 and rect.y1 == 0
        assert rect.x2 == 9 and rect.y2 == 4

    def test_no_change(self):
        fb = b"\x00" * 100
        rect = renderer.compute_dirty_rect(fb, fb, 10, 5)
        assert rect is None

    def test_partial_change(self):
        # 10x5 framebuffer, 4 bytes per pixel (for simplicity use uint8)
        cur = bytearray(50)  # all zeros
        pen = bytearray(50)
        # Change pixel at (3, 2) -> index 23
        pen[23] = 0xFF
        rect = renderer.compute_dirty_rect(bytes(cur), bytes(pen), 10, 5)
        assert rect is not None
        assert rect.x1 <= 3 <= rect.x2
        assert rect.y1 <= 2 <= rect.y2

    def test_size_mismatch_forces_full(self):
        rect = renderer.compute_dirty_rect(b"\x00" * 10, b"\x00" * 20, 10, 5)
        assert rect is not None
        assert rect.x1 == 0 and rect.y2 == 4

    def test_dirty_rect_is_empty(self):
        rect = renderer.DirtyRect(5, 5, 3, 3)
        assert rect.is_empty()

    def test_dirty_rect_not_empty(self):
        rect = renderer.DirtyRect(0, 0, 10, 10)
        assert not rect.is_empty()
        assert rect.width == 11
        assert rect.height == 11


class TestScreenRenderer:
    def test_update_returns_none_on_unchanged(self):
        r = renderer.ScreenRenderer()
        fb = renderer.render_solid_color(0, 0, 0)
        r.update(fb)
        result = r.update(fb)
        assert result is None

    def test_update_returns_dirty_rect_on_change(self):
        r = renderer.ScreenRenderer()
        fb1 = renderer.render_solid_color(0, 0, 0)
        fb2 = renderer.render_solid_color(255, 0, 0)
        r.update(fb1)
        result = r.update(fb2)
        assert result is not None
        rect, payload = result
        assert rect.x1 == 0 and rect.y1 == 0
        assert rect.x2 == SCREEN_WIDTH - 1 and rect.y2 == SCREEN_HEIGHT - 1

    def test_force_full_redraw(self):
        r = renderer.ScreenRenderer()
        fb = renderer.render_solid_color(0, 0, 0)
        r.update(fb)
        r.force_full_redraw()
        result = r.update(fb)
        assert result is not None  # full redraw forced

    def test_wrong_size_raises(self):
        r = renderer.ScreenRenderer()
        with pytest.raises(ValueError, match="framebuffer must be"):
            r.update(b"\x00" * 10)


class TestExtractRegion:
    def test_extract_2x2_from_4x4(self):
        import numpy as np
        # 4x4 framebuffer with uint16 values
        fb = np.arange(16, dtype=np.uint16).reshape(4, 4).tobytes()
        rect = renderer.DirtyRect(1, 1, 2, 2)  # 2x2 region
        region = renderer.extract_region(fb, 4, 4, rect, endian="little")
        arr = np.frombuffer(region, dtype="<u2").reshape(2, 2)
        expected = np.array([[5, 6], [9, 10]], dtype=np.uint16)
        assert np.array_equal(arr, expected)
