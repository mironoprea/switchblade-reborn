"""Native HID brightness control for the DeathStalker Ultimate."""

from __future__ import annotations

from collections.abc import Callable

from .protocol import build_brightness_report

KEY_LCD_CHANNEL = 2
KEYBOARD_CHANNEL = 1

VID = 0x1532
PID = 0x0114
HID_INTERFACE = 2
REPORT_LENGTH = 90


class BrightnessError(RuntimeError):
    pass


class BrightnessController:
    """Send the captured 90-byte brightness report through HID interface 2."""

    def __init__(
        self,
        *,
        enumerate_devices: Callable | None = None,
        device_factory: Callable | None = None,
    ) -> None:
        if enumerate_devices is None or device_factory is None:
            try:
                import hid
            except ImportError as exc:
                raise BrightnessError("hidapi is not installed") from exc
            enumerate_devices = enumerate_devices or hid.enumerate
            device_factory = device_factory or hid.device
        self._enumerate = enumerate_devices
        self._device_factory = device_factory

    def set_key_lcd_brightness(self, percent: int) -> None:
        self.set_channel(KEY_LCD_CHANNEL, percent)

    def set_keyboard_brightness(self, percent: int) -> None:
        self.set_channel(KEYBOARD_CHANNEL, percent)

    def set_channel(self, channel: int, percent: int) -> None:
        if channel not in (KEYBOARD_CHANNEL, KEY_LCD_CHANNEL):
            raise ValueError("brightness channel must be 1 or 2")
        if not 0 <= percent <= 100:
            raise ValueError("brightness must be 0-100")
        report = build_brightness_report(channel, percent)
        errors: list[str] = []
        candidates = [
            info for info in self._enumerate(VID, PID)
            if info.get("interface_number") == HID_INTERFACE
        ]
        if not candidates:
            raise BrightnessError("DeathStalker HID interface 2 was not found")
        for info in candidates:
            device = self._device_factory()
            try:
                device.open_path(info["path"])
                written = device.send_feature_report(report)
                if written == REPORT_LENGTH:
                    return
                errors.append(f"feature report returned {written}")
            except OSError as exc:
                errors.append(str(exc))
            finally:
                try:
                    device.close()
                except OSError:
                    pass
        detail = "; ".join(errors) or "no compatible HID collection accepted the report"
        raise BrightnessError(f"brightness command failed: {detail}")
