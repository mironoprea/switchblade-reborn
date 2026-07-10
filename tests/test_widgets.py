"""Tests for app.widgets - pure logic, no hardware needed."""

from PIL import Image
from app.widgets import (
    render_clock,
    render_cpu_ram,
    render_now_playing,
    render_widget_board,
)
from app.protocol import SCREEN_WIDTH, SCREEN_HEIGHT


class TestRenderClock:
    def test_returns_dirty_rect(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        rect = render_clock(img, 10, 10)
        assert len(rect) == 4
        x1, y1, x2, y2 = rect
        assert x1 <= 10
        assert y1 <= 20  # font ascent may push y1 slightly below 10
        assert x2 > x1
        assert y2 >= y1

    def test_draws_on_image(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        render_clock(img, 10, 10)
        # Some pixels should be non-black (white text)
        # Check that some pixels are non-black (text drawn)
        found = False
        for y in range(SCREEN_HEIGHT):
            for x in range(0, SCREEN_WIDTH, 10):
                if img.getpixel((x, y)) != (0, 0, 0):
                    found = True
                    break
            if found:
                break
        assert found


class TestRenderCpuRam:
    def test_returns_dirty_rect(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        rect = render_cpu_ram(img, 10, 10)
        assert len(rect) == 4

    def test_draws_on_image(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        render_cpu_ram(img, 10, 10)
        # Check that some pixels are non-black (text drawn)
        found = False
        for y in range(SCREEN_HEIGHT):
            for x in range(0, SCREEN_WIDTH, 10):
                if img.getpixel((x, y)) != (0, 0, 0):
                    found = True
                    break
            if found:
                break
        assert found


class TestRenderNowPlaying:
    def test_returns_dirty_rect(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        rect = render_now_playing(img, 10, 10)
        assert len(rect) == 4

    def test_draws_on_image(self):
        img = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0))
        render_now_playing(img, 10, 10)
        # Check that some pixels are non-black (text drawn)
        found = False
        for y in range(SCREEN_HEIGHT):
            for x in range(0, SCREEN_WIDTH, 10):
                if img.getpixel((x, y)) != (0, 0, 0):
                    found = True
                    break
            if found:
                break
        assert found


class TestRenderWidgetBoard:
    def test_default_image(self):
        config = {"type": "widget_board", "widgets": []}
        img, dirty_rects = render_widget_board(config)
        assert img.size == (SCREEN_WIDTH, SCREEN_HEIGHT)
        assert dirty_rects == []

    def test_with_widgets(self):
        config = {
            "type": "widget_board",
            "widgets": [
                {"type": "clock", "x": 10, "y": 10},
                {"type": "cpu_ram", "x": 10, "y": 50},
            ],
        }
        img, dirty_rects = render_widget_board(config)
        assert img.size == (SCREEN_WIDTH, SCREEN_HEIGHT)
        assert len(dirty_rects) == 2

    def test_with_base_image(self):
        base = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), (30, 30, 30))
        config = {"type": "widget_board", "widgets": []}
        img, dirty_rects = render_widget_board(config, base_image=base)
        assert img.size == (SCREEN_WIDTH, SCREEN_HEIGHT)

    def test_unknown_widget_type_skipped(self):
        config = {
            "type": "widget_board",
            "widgets": [
                {"type": "unknown", "x": 10, "y": 10},
            ],
        }
        img, dirty_rects = render_widget_board(config)
        assert len(dirty_rects) == 0
