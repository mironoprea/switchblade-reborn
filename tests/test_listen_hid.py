"""Tests for the HID diagnostic listener helpers."""

from tools import listen_hid


def test_keyboard_collection_detection():
    assert listen_hid._is_keyboard_collection({"usage_page": 0x01, "usage": 0x06})
    assert not listen_hid._is_keyboard_collection({"usage_page": 0x0C, "usage": 0x01})


def test_label_formats_bytes_path():
    label = listen_hid._label(
        {
            "interface_number": 1,
            "usage_page": 0x0C,
            "usage": 0x01,
            "path": b"abc",
        }
    )

    assert "interface=1" in label
    assert "usage_page=0x000c" in label
    assert "path=abc" in label
