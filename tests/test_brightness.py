import pytest

from app.brightness import BrightnessController, BrightnessError
from app.protocol import build_brightness_report


def test_build_key_lcd_brightness_report_from_capture():
    report = build_brightness_report(2, 40)
    assert len(report) == 90
    assert report[:12] == bytes.fromhex("00 00 ff 00 00 00 03 09 01 00 02 66")
    assert report[88:] == bytes.fromhex("6f 00")


def test_build_keyboard_brightness_report_from_capture():
    report = build_brightness_report(1, 40)
    assert report[:12] == bytes.fromhex("00 00 ff 00 00 00 03 09 01 00 01 66")
    assert report[88:] == bytes.fromhex("6c 00")


def test_build_brightness_query_report():
    report = build_brightness_report(2, 100, query=True)
    assert report[:12] == bytes.fromhex("00 00 ff 00 00 00 03 09 81 00 02 00")
    assert report[88:] == bytes.fromhex("89 00")


@pytest.mark.parametrize("channel,percent", [(0, 50), (3, 50), (1, -1), (2, 101)])
def test_build_brightness_report_rejects_invalid_values(channel, percent):
    with pytest.raises(ValueError):
        build_brightness_report(channel, percent)


class FakeHidDevice:
    def __init__(self, result=90):
        self.result = result
        self.path = None
        self.report = None
        self.closed = False

    def open_path(self, path):
        self.path = path

    def send_feature_report(self, report):
        self.report = report
        return self.result

    def close(self):
        self.closed = True


def test_controller_set_key_channel():
    device = FakeHidDevice()
    controller = BrightnessController(
        enumerate_devices=lambda vid, pid: [{"path": b"mi02", "interface_number": 2}],
        device_factory=lambda: device,
    )
    controller.set_key_lcd_brightness(75)
    assert device.path == b"mi02"
    assert device.report == build_brightness_report(2, 75)
    assert device.closed


def test_controller_surfaces_hid_failure():
    controller = BrightnessController(
        enumerate_devices=lambda vid, pid: [{"path": b"mi02", "interface_number": 2}],
        device_factory=lambda: FakeHidDevice(result=-1),
    )
    with pytest.raises(BrightnessError, match="feature report returned -1"):
        controller.set_keyboard_brightness(50)


def test_controller_ignores_other_interfaces():
    controller = BrightnessController(
        enumerate_devices=lambda vid, pid: [{"path": b"mi01", "interface_number": 1}],
        device_factory=FakeHidDevice,
    )
    with pytest.raises(BrightnessError, match="interface 2"):
        controller.set_key_lcd_brightness(50)
