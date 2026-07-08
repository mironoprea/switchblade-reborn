"""
USB transport for the Razer DeathStalker Ultimate Switchblade interface.

Uses pyusb (libusb-1.0 backend) to find, claim, and communicate with the
vendor-specific interface.  Handles reconnection polling, safety guards
(refuses HID interfaces), and graceful error recovery.

Only this module touches pyusb.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import usb.core
import usb.util

from .protocol import VENDOR_VID, VENDOR_PID, BULK_OUT_EP, BULK_IN_EP

logger = logging.getLogger(__name__)

HID_CLASS = 0x03
RETRY_INTERVAL = 2.0  # seconds between reconnection attempts
USB_TIMEOUT = 5000   # ms


# ---------------------------------------------------------------------------
# Device info
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Describes the discovered vendor interface."""
    vendor_interface: int
    out_endpoint: int
    in_endpoint: int
    max_out_packet: int
    max_in_packet: int

    def __str__(self) -> str:
        return (
            f"interface={self.vendor_interface} "
            f"OUT=0x{self.out_endpoint:02x} "
            f"IN=0x{self.in_endpoint:02x}"
        )


# ---------------------------------------------------------------------------
# Connection states
# ---------------------------------------------------------------------------

DISCONNECTED = "DISCONNECTED"
CLAIMING = "CLAIMING"
INITIALIZING = "INITIALIZING"
READY = "READY"
ERROR_FATAL = "ERROR_FATAL"


# ---------------------------------------------------------------------------
# UsbLink
# ---------------------------------------------------------------------------

class UsbLink:
    """Manages the USB connection to the Switchblade vendor interface.

    The caller drives a polling loop: call :meth:`poll` to attempt connection
    or detect disconnection.  Check :attr:`state` for the current state.

    Safety: never claims a HID-class interface.
    """

    def __init__(
        self,
        vid: int = VENDOR_VID,
        pid: int = VENDOR_PID,
        interface: Optional[int] = None,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.preferred_interface = interface
        self.dev = None
        self.info: Optional[DeviceInfo] = None
        self.state = DISCONNECTED
        self._last_try = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> str:
        """Advance the state machine.  Returns the current state."""
        if self.state in (READY, INITIALIZING, CLAIMING):
            # Check if device still present
            if not self._device_present():
                logger.info("Device disconnected (lost USB handle).")
                self._release()
                self.state = DISCONNECTED

        if self.state == DISCONNECTED:
            now = time.time()
            if now - self._last_try >= RETRY_INTERVAL:
                self._last_try = now
                self._try_connect()

        return self.state

    def is_ready(self) -> bool:
        return self.state == READY

    def write(self, data: bytes) -> int:
        """Write data to the bulk OUT endpoint.  Returns bytes written."""
        if self.state not in (READY, INITIALIZING):
            raise ConnectionError(f"Device not ready (state={self.state})")
        if self.dev is None or self.info is None:
            raise ConnectionError("No device handle")
        try:
            total = 0
            offset = 0
            chunk = self.info.max_out_packet
            while offset < len(data):
                end = min(offset + chunk, len(data))
                written = self.dev.write(
                    self.info.out_endpoint,
                    data[offset:end],
                    timeout=USB_TIMEOUT,
                )
                total += written
                offset = end
            return total
        except usb.core.USBError as exc:
            logger.error("USB write error: %s", exc)
            self._release()
            self.state = DISCONNECTED
            raise ConnectionError(str(exc)) from exc

    def read(self, length: int = 64, timeout: int = USB_TIMEOUT) -> bytes:
        """Read data from the bulk IN endpoint."""
        if self.state not in (READY, INITIALIZING):
            raise ConnectionError(f"Device not ready (state={self.state})")
        if self.dev is None or self.info is None:
            raise ConnectionError("No device handle")
        try:
            data = self.dev.read(
                self.info.in_endpoint,
                length,
                timeout=timeout,
            )
            return bytes(data)
        except usb.core.USBError as exc:
            if "timeout" in str(exc).lower():
                return b""
            logger.error("USB read error: %s", exc)
            self._release()
            self.state = DISCONNECTED
            raise ConnectionError(str(exc)) from exc

    def mark_ready(self) -> None:
        """Called by daemon after init/test blit confirms the device works."""
        if self.state == INITIALIZING:
            self.state = READY
            logger.info("Device state: READY")

    def disconnect(self) -> None:
        """Release the device and go to DISCONNECTED."""
        self._release()
        self.state = DISCONNECTED

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_connect(self) -> None:
        self.state = CLAIMING
        logger.info("Device state: CLAIMING")
        try:
            self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)
            if self.dev is None:
                logger.debug("Device not found (VID=%04x PID=%04x)", self.vid, self.pid)
                self.state = DISCONNECTED
                return

            info = self._find_vendor_interface()
            if info is None:
                logger.error("No suitable vendor interface found on the device.")
                self.state = ERROR_FATAL
                return

            # Claim the interface
            try:
                usb.util.claim_interface(self.dev, info.vendor_interface)
            except usb.core.USBError as exc:
                logger.error("Cannot claim interface %d: %s", info.vendor_interface, exc)
                logger.error("Another program may own the device. Exiting.")
                self.state = ERROR_FATAL
                return

            self.info = info
            self.state = INITIALIZING
            logger.info("Device state: INITIALIZING — %s", info)

        except usb.core.USBError as exc:
            logger.error("USB error during connect: %s", exc)
            self._release()
            self.state = DISCONNECTED

    def _find_vendor_interface(self) -> Optional[DeviceInfo]:
        """Scan interfaces and find the vendor-specific one."""
        cfg = self.dev.get_active_configuration()

        candidates = []
        for iface in cfg:
            cls = iface.bInterfaceClass

            # Safety guard: never touch HID
            if cls == HID_CLASS:
                logger.debug(
                    "Skipping HID interface %d (class 0x03)", iface.bInterfaceNumber
                )
                continue

            # Find bulk endpoints
            out_ep = None
            in_ep = None
            for ep in iface:
                ep_addr = ep.bEndpointAddress
                if ep.bmAttributes == 2:  # Bulk transfer type
                    if ep_addr & 0x80:  # IN direction
                        in_ep = ep_addr
                    else:
                        out_ep = ep_addr

            if out_ep is None and in_ep is None:
                continue

            candidates.append((iface, out_ep, in_ep))

        if not candidates:
            return None

        # Pick preferred interface if specified
        if self.preferred_interface is not None:
            for iface, out_ep, in_ep in candidates:
                if iface.bInterfaceNumber == self.preferred_interface:
                    return self._build_info(iface, out_ep, in_ep)

        # Otherwise pick the first vendor-specific (0xFF) interface, else first
        for iface, out_ep, in_ep in candidates:
            if iface.bInterfaceClass == 0xFF:
                return self._build_info(iface, out_ep, in_ep)

        iface, out_ep, in_ep = candidates[0]
        return self._build_info(iface, out_ep, in_ep)

    @staticmethod
    def _build_info(iface, out_ep, in_ep) -> DeviceInfo:
        max_out = 512
        max_in = 512
        for ep in iface:
            ep_addr = ep.bEndpointAddress
            if ep_addr == out_ep:
                max_out = ep.wMaxPacketSize
            if ep_addr == in_ep:
                max_in = ep.wMaxPacketSize
        return DeviceInfo(
            vendor_interface=iface.bInterfaceNumber,
            out_endpoint=out_ep or BULK_OUT_EP,
            in_endpoint=in_ep or BULK_IN_EP,
            max_out_packet=max_out,
            max_in_packet=max_in,
        )

    def _device_present(self) -> bool:
        if self.dev is None:
            return False
        try:
            _ = self.dev.get_active_configuration()
            return True
        except usb.core.USBError:
            return False

    def _release(self) -> None:
        if self.dev is not None and self.info is not None:
            try:
                usb.util.release_interface(self.dev, self.info.vendor_interface)
            except Exception as exc:
                logger.debug("Release failed (ok): %s", exc)
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
        self.dev = None
        self.info = None


# ---------------------------------------------------------------------------
# Synapse guard
# ---------------------------------------------------------------------------

SYNAPSE_PROCESS_NAMES = {
    "razer synapse",
    "rzsynapse",
    "rzsynapse.exe",
    "razer synapse 2.0",
    "razerconfigurator",
    "rzcredentialprovider",
}


def is_synapse_running() -> bool:
    """Check if Razer Synapse processes are running."""
    try:
        import psutil
    except ImportError:
        return False

    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name", "")
        if not name:
            continue
        lower = name.lower()
        if any(s in lower for s in SYNAPSE_PROCESS_NAMES):
            return True
    return False
