"""Tests for the USB enumeration diagnostic helpers."""

from tools import enumerate as enumerate_tool


def test_safe_get_string_returns_na_for_missing_index():
    assert enumerate_tool._safe_get_string(object(), 0) == "N/A"


def test_safe_get_string_keeps_enumeration_alive_on_usb_error(monkeypatch):
    def _raise_usb_error(dev, index):
        raise enumerate_tool.usb.core.USBError("Invalid parameter")

    monkeypatch.setattr(enumerate_tool.usb.util, "get_string", _raise_usb_error)

    assert enumerate_tool._safe_get_string(object(), 1).startswith("<unavailable:")
