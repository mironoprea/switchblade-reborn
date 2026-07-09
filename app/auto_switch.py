"""
Automatic profile switching based on the foreground window's exe name.

Polls the foreground window every 2 seconds via pywin32.
On non-Windows, this is a no-op.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    try:
        import win32gui
        import win32process
        import ctypes
        _HAS_WIN32 = True
    except ImportError:
        _HAS_WIN32 = False
else:
    _HAS_WIN32 = False


def get_foreground_exe() -> Optional[str]:
    """Return the exe name of the foreground window, or None."""
    if not (IS_WINDOWS and _HAS_WIN32):
        return None

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return None

        # Get process exe name via process handle
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return None

        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_uint(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:
        logger.debug("get_foreground_exe error: %s", exc)
        return None

    return None


class AutoSwitcher:
    """Polls foreground window and triggers profile switch when mapped."""

    def __init__(
        self,
        auto_switch_map: dict[str, str],
        default_profile: str,
        on_switch: Callable[[str], None],
        *,
        poll_interval: float = 2.0,
    ) -> None:
        self._map = {k.lower(): v for k, v in auto_switch_map.items()}
        self._default = default_profile
        self._on_switch = on_switch
        self._poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._current_profile = default_profile

    def start(self) -> None:
        if not (IS_WINDOWS and _HAS_WIN32):
            logger.info("Auto-switch needs Windows + pywin32; not starting.")
            return
        if not self._map:
            logger.info("Auto-switch map is empty; not starting.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Auto-switcher started.")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    def update_map(self, auto_switch_map: dict[str, str], default_profile: str) -> None:
        self._map = {k.lower(): v for k, v in auto_switch_map.items()}
        self._default = default_profile

    def _run(self) -> None:
        while not self._stop.is_set():
            exe = get_foreground_exe()
            exe_lower = exe.lower() if exe else ""

            target = self._map.get(exe_lower, self._default)
            if target != self._current_profile:
                logger.info("Auto-switch: %s -> profile '%s'", exe_lower, target)
                self._current_profile = target
                try:
                    self._on_switch(target)
                except Exception as exc:
                    logger.error("Auto-switch callback error: %s", exc)

            self._stop.wait(self._poll_interval)
