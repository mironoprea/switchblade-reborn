"""
Input listener: reads key events from the vendor IN endpoint and dispatches
callbacks.  Runs in its own thread to avoid blocking the main loop.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .protocol import parse_key_event, KeyEvent
from .usb_link import UsbLink

logger = logging.getLogger(__name__)

DEBOUNCE_MS = 150  # ignore repeats within this window


class InputListener:
    """Polls the vendor IN endpoint for key events in a worker thread."""

    def __init__(
        self,
        link: UsbLink,
        callback: Callable[[KeyEvent], None],
        *,
        read_timeout: int = 100,
    ) -> None:
        self._link = link
        self._callback = callback
        self._read_timeout = read_timeout
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_key_time: dict[int, float] = {}
        self._last_key_state: dict[int, bool] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Input listener started.")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.info("Input listener stopped.")

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._link.is_ready():
                time.sleep(0.1)
                continue
            info = self._link.info
            if info is not None and info.in_endpoint is None:
                # No vendor IN endpoint; read() would return instantly, so pace
                # the loop to avoid busy-spinning a CPU core.  Any key events
                # arrive over HID, not this path.
                time.sleep(0.5)
                continue
            try:
                data = self._link.read(length=512, timeout=self._read_timeout)
            except ConnectionError:
                time.sleep(0.5)
                continue
            except Exception as exc:
                logger.debug("Input read error: %s", exc)
                time.sleep(0.1)
                continue

            if not data:
                continue

            event = parse_key_event(data)
            if event is None:
                logger.debug("Unknown packet: %s", data.hex())
                continue

            self._dispatch(event)

    def _dispatch(self, event: KeyEvent) -> None:
        now = time.time()
        key = event.key_index

        # Debounce: only act on key-down, ignore repeats within 150ms
        if event.pressed:
            last = self._last_key_time.get(key, 0)
            last_state = self._last_key_state.get(key, False)
            if last_state and (now - last) * 1000 < DEBOUNCE_MS:
                return
            self._last_key_time[key] = now
            self._last_key_state[key] = True
        else:
            self._last_key_state[key] = False

        logger.info("Key event: %s", event)
        try:
            self._callback(event)
        except Exception as exc:
            logger.error("Callback error: %s", exc)
