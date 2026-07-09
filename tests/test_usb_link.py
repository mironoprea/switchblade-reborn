"""Tests for app.usb_link — transport logic, no hardware needed.

These require pyusb (for the real USBError/USBTimeoutError types) and are
skipped when it isn't installed.
"""

import pytest
from app import usb_link

usb = usb_link.usb


def _make_link(dev):
    link = usb_link.UsbLink()
    link.state = usb_link.READY
    link.dev = dev
    link.info = usb_link.DeviceInfo(
        vendor_interface=3,
        out_endpoint=0x01,
        in_endpoint=0x82,
        max_out_packet=512,
        max_in_packet=512,
    )
    return link


@pytest.mark.skipif(usb is None, reason="pyusb not installed")
class TestReadTimeoutClassification:
    def test_timeout_returns_empty_and_stays_ready(self):
        # libusb reports a timeout as "Operation timed out" (no "timeout"
        # substring), so it must be classified by exception type.
        class _Dev:
            def read(self, *a, **k):
                raise usb.core.USBTimeoutError("Operation timed out")

        link = _make_link(_Dev())
        assert link.read(length=64, timeout=100) == b""
        # A timeout must NOT tear the link down — otherwise an idle device
        # disconnects the instant it becomes READY.
        assert link.state == usb_link.READY

    def test_real_error_tears_down(self):
        class _Dev:
            def read(self, *a, **k):
                raise usb.core.USBError("pipe error")

        link = _make_link(_Dev())
        with pytest.raises(ConnectionError):
            link.read(length=64, timeout=100)
        assert link.state == usb_link.DISCONNECTED
