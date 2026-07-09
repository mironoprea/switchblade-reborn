"""Tests for app.usb_link — transport logic, no hardware needed.

These require pyusb (for the real USBError/USBTimeoutError types) and are
skipped when it isn't installed.
"""

import pytest
from app import usb_link

usb = usb_link.usb


class _Endpoint:
    def __init__(self, address, max_packet=512, attributes=2):
        self.bEndpointAddress = address
        self.wMaxPacketSize = max_packet
        self.bmAttributes = attributes


class _Interface:
    bInterfaceNumber = 3
    bInterfaceClass = 0xFF

    def __init__(self, endpoints):
        self._endpoints = endpoints

    def __iter__(self):
        return iter(self._endpoints)


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


def test_build_info_prefers_canonical_out_endpoint_when_multiple_outs():
    iface = _Interface([_Endpoint(0x02), _Endpoint(0x01)])

    info = usb_link.UsbLink._build_info(iface, list(iface), [])

    assert info.out_endpoint == 0x01
    assert info.in_endpoint is None
    assert str(info) == "interface=3 OUT=0x01 IN=none"


def test_read_returns_empty_when_no_vendor_in_endpoint():
    class _Dev:
        def read(self, *a, **k):
            raise AssertionError("read should not be attempted without an IN endpoint")

    link = _make_link(_Dev())
    link.info.in_endpoint = None

    assert link.read(length=64, timeout=100) == b""


def test_write_transfer_sends_single_bulk_transfer():
    class _Dev:
        def __init__(self):
            self.calls = []

        def write(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return len(args[1])

    dev = _Dev()
    link = _make_link(dev)
    payload = b"x" * 1500

    assert link.write_transfer(payload) == len(payload)
    assert len(dev.calls) == 1
    assert dev.calls[0][0][0] == 0x01
    assert dev.calls[0][0][1] == payload
