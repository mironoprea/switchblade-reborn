"""
USB transport for the Razer DeathStalker Ultimate Switchblade interface.

Uses pyusb (libusb-1.0 backend) to find, claim, and communicate with the
vendor-specific interface.  Handles reconnection polling, safety guards
(refuses HID interfaces), and graceful error recovery.

Only this module touches pyusb.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import usb.core
    import usb.util
except ImportError:
    usb = None

try:
    import libusb_package
    _BACKEND = libusb_package.get_libusb1_backend()
except Exception:
    _BACKEND = None

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
    in_endpoint: Optional[int]
    max_out_packet: int
    max_in_packet: int

    def __str__(self) -> str:
        in_endpoint = (
            f"0x{self.in_endpoint:02x}" if self.in_endpoint is not None else "none"
        )
        return (
            f"interface={self.vendor_interface} "
            f"OUT=0x{self.out_endpoint:02x} "
            f"IN={in_endpoint}"
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
        self._io_lock = threading.Lock()
        # Serializes teardown + state transitions across the main-loop thread
        # and the input-listener thread so one can't null out ``dev`` while the
        # other is mid-use.
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> str:
        """Advance the state machine.  Returns the current state."""
        if self.state in (READY, INITIALIZING, CLAIMING):
            # Check if device still present
            if not self._device_present():
                logger.info("Device disconnected (lost USB handle).")
                self._teardown()

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
        # Snapshot the handle so a concurrent teardown can't null it mid-use.
        dev = self.dev
        info = self.info
        if dev is None or info is None:
            raise ConnectionError("No device handle")
        try:
            with self._io_lock:
                total = 0
                offset = 0
                chunk = info.max_out_packet
                while offset < len(data):
                    end = min(offset + chunk, len(data))
                    written = dev.write(
                        info.out_endpoint,
                        data[offset:end],
                        timeout=USB_TIMEOUT,
                    )
                    total += written
                    offset = end
                return total
        except Exception as exc:
            if usb is not None and isinstance(exc, usb.core.USBError):
                logger.error("USB write error: %s", exc)
                self._teardown()
                raise ConnectionError(str(exc)) from exc
            raise

    def read(self, length: int = 64, timeout: int = USB_TIMEOUT) -> bytes:
        """Read data from the bulk IN endpoint.

        A read timeout is *not* an error — an idle device has nothing to send,
        so timeouts return ``b""``.  Only genuine transfer errors tear down the
        link.
        """
        if self.state not in (READY, INITIALIZING):
            raise ConnectionError(f"Device not ready (state={self.state})")
        # Snapshot the handle so a concurrent teardown can't null it mid-use.
        dev = self.dev
        info = self.info
        if dev is None or info is None:
            raise ConnectionError("No device handle")
        if info.in_endpoint is None:
            return b""
        try:
            with self._io_lock:
                data = dev.read(
                    info.in_endpoint,
                    length,
                    timeout=timeout,
                )
                return bytes(data)
        except Exception as exc:
            if usb is not None and isinstance(exc, usb.core.USBTimeoutError):
                # libusb reports this as "Operation timed out" — the substring
                # "timeout" is absent, so it must be classified by type.
                return b""
            if usb is not None and isinstance(exc, usb.core.USBError):
                # Belt-and-suspenders: some backends surface a timeout as a plain
                # USBError with errno 110 (Linux ETIMEDOUT) / 10060 (WinUSB).
                if getattr(exc, "errno", None) in (110, 10060):
                    return b""
                logger.error("USB read error: %s", exc)
                self._teardown()
                raise ConnectionError(str(exc)) from exc
            raise

    def mark_ready(self) -> None:
        """Called by daemon after init/test blit confirms the device works."""
        if self.state == INITIALIZING:
            self.state = READY
            logger.info("Device state: READY")

    def disconnect(self) -> None:
        """Release the device and go to DISCONNECTED."""
        self._teardown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_connect(self) -> None:
        if usb is None:
            logger.error("pyusb not installed. Install with: pip install pyusb libusb-package")
            self.state = ERROR_FATAL
            return
        self.state = CLAIMING
        logger.info("Device state: CLAIMING")
        try:
            self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid, backend=_BACKEND)
            if self.dev is None:
                logger.debug("Device not found (VID=%04x PID=%04x)", self.vid, self.pid)
                self.state = DISCONNECTED
                return

            info = self._find_vendor_interface()
            if info is None:
                logger.error("No suitable vendor interface found on the device.")
                self.state = ERROR_FATAL
                return

            # On Linux a kernel driver may be bound to the interface; detach it
            # first or claim_interface fails with EBUSY.  (Windows uses WinUSB,
            # which has no kernel driver to detach.)
            if os.name != "nt":
                try:
                    if self.dev.is_kernel_driver_active(info.vendor_interface):
                        self.dev.detach_kernel_driver(info.vendor_interface)
                        logger.info(
                            "Detached kernel driver from interface %d.",
                            info.vendor_interface,
                        )
                except (NotImplementedError, usb.core.USBError) as exc:
                    logger.debug("Kernel driver detach skipped: %s", exc)

            # Claim the interface
            try:
                usb.util.claim_interface(self.dev, info.vendor_interface)
            except Exception as exc:
                logger.error("Cannot claim interface %d: %s", info.vendor_interface, exc)
                logger.error("Another program may own the device. Exiting.")
                self.state = ERROR_FATAL
                return

            self.info = info
            self.state = INITIALIZING
            logger.info("Device state: INITIALIZING — %s", info)

        except Exception as exc:
            if usb is not None and isinstance(exc, usb.core.USBError):
                logger.error("USB error during connect: %s", exc)
                self._teardown()
            else:
                raise

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
            out_eps = []
            in_eps = []
            for ep in iface:
                ep_addr = ep.bEndpointAddress
                if (ep.bmAttributes & 0x03) == 2:  # Bulk transfer type
                    if ep_addr & 0x80:  # IN direction
                        in_eps.append(ep)
                    else:
                        out_eps.append(ep)

            if not out_eps:
                continue

            candidates.append((iface, out_eps, in_eps))

        if not candidates:
            return None

        # Pick preferred interface if specified
        if self.preferred_interface is not None:
            for iface, out_eps, in_eps in candidates:
                if iface.bInterfaceNumber == self.preferred_interface:
                    return self._build_info(iface, out_eps, in_eps)

        # Otherwise pick the first vendor-specific (0xFF) interface, else first
        for iface, out_eps, in_eps in candidates:
            if iface.bInterfaceClass == 0xFF:
                return self._build_info(iface, out_eps, in_eps)

        iface, out_eps, in_eps = candidates[0]
        return self._build_info(iface, out_eps, in_eps)

    @staticmethod
    def _select_endpoint(endpoints, preferred: int):
        for ep in endpoints:
            if ep.bEndpointAddress == preferred:
                return ep
        return endpoints[0] if endpoints else None

    @classmethod
    def _build_info(cls, iface, out_eps, in_eps) -> DeviceInfo:
        out_ep = cls._select_endpoint(out_eps, BULK_OUT_EP)
        in_ep = cls._select_endpoint(in_eps, BULK_IN_EP)
        if out_ep is None:
            raise ValueError("vendor interface has no bulk OUT endpoint")

        return DeviceInfo(
            vendor_interface=iface.bInterfaceNumber,
            out_endpoint=out_ep.bEndpointAddress,
            in_endpoint=in_ep.bEndpointAddress if in_ep is not None else None,
            max_out_packet=out_ep.wMaxPacketSize,
            max_in_packet=in_ep.wMaxPacketSize if in_ep is not None else 0,
        )

    def _device_present(self) -> bool:
        # Snapshot: a concurrent teardown may null ``dev`` between the check and
        # the transfer below.  Any failure (USBError, or AttributeError if it was
        # nulled) means "not present".
        dev = self.dev
        if dev is None or usb is None:
            return False
        try:
            _ = dev.get_active_configuration()
            return True
        except Exception:
            return False

    def _teardown(self) -> None:
        """Release the device and mark DISCONNECTED, once, thread-safely.

        Both the main-loop and input-listener threads can hit an error path at
        the same time; the lock ensures only one performs the release.
        """
        with self._state_lock:
            if self.state == DISCONNECTED and self.dev is None:
                return
            self._release()
            self.state = DISCONNECTED

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
