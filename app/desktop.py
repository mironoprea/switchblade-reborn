"""Consumer Windows entry point: tray icon, logging, and single-instance UI."""

from __future__ import annotations

import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from PIL import Image, ImageDraw

from .daemon import Daemon
from .paths import APP_NAME, bootstrap_user_data, log_file, profiles_file, resource_root

CONTROL_URL = "http://127.0.0.1:8377"
MUTEX_NAME = "Local\\SwitchbladeReborn.SingleInstance"
STARTUP_VALUE = "SwitchbladeReborn"

logger = logging.getLogger(__name__)


def configure_logging() -> Path:
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        handler = RotatingFileHandler(
            path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)
    return path


def _acquire_single_instance():
    if os.name != "nt":
        return None, True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already_exists = kernel32.GetLastError() == 183
    return handle, not already_exists


def _release_single_instance(handle) -> None:
    if handle and os.name == "nt":
        ctypes.windll.kernel32.CloseHandle(handle)


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{executable}" -m app.desktop'


def startup_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        ) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_VALUE)
        return bool(value)
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    if os.name != "nt":
        return
    import winreg

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
    ) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_VALUE, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE)
            except FileNotFoundError:
                pass


def _open_control_panel(*_args) -> None:
    webbrowser.open(CONTROL_URL)


def _open_logs(*_args) -> None:
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _icon_image() -> Image.Image:
    asset = resource_root() / "assets" / "app-icon.png"
    if asset.is_file():
        return Image.open(asset).convert("RGBA")
    image = Image.new("RGBA", (256, 256), (8, 16, 30, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((26, 38, 230, 218), radius=32, fill=(14, 32, 55, 255))
    draw.polygon([(126, 49), (70, 139), (116, 139), (94, 207), (184, 111), (137, 111)], fill=(34, 211, 238, 255))
    return image


def _wait_for_web(timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{CONTROL_URL}/api/status", timeout=0.5) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def main() -> int:
    bootstrap_user_data()
    if "--smoke-test" in sys.argv:
        # Packaging verification: exercise bundled imports and writable-data
        # setup without starting the hardware loop or tray UI.
        from . import actions, input_listener, protocol, renderer, widgets
        from .webui.app import create_app
        _ = (actions, input_listener, protocol, renderer, widgets, create_app)
        return 0
    configure_logging()
    mutex, acquired = _acquire_single_instance()
    if not acquired:
        _open_control_panel()
        _release_single_instance(mutex)
        return 0

    daemon = Daemon(str(profiles_file()), web=True)
    startup_error: list[BaseException] = []

    def run_daemon() -> None:
        try:
            daemon.start()
        except BaseException as exc:  # keep the tray responsive and log startup failure
            startup_error.append(exc)
            logger.exception("Application runtime stopped unexpectedly")

    worker = threading.Thread(target=run_daemon, name="switchblade-daemon", daemon=True)
    worker.start()

    if not _wait_for_web():
        daemon.stop()
        _release_single_instance(mutex)
        message = str(startup_error[0]) if startup_error else "The local control panel did not start."
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
        return 1

    _open_control_panel()

    try:
        import pystray
    except ImportError:
        logger.warning("pystray is not installed; running without a tray icon")
        try:
            while worker.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            daemon.stop()
        _release_single_instance(mutex)
        return 0

    def toggle_startup(_icon, _item) -> None:
        set_startup_enabled(not startup_enabled())

    def quit_app(icon, _item) -> None:
        daemon.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Control Panel", _open_control_panel, default=True),
        pystray.MenuItem(
            "Start with Windows",
            toggle_startup,
            checked=lambda _item: startup_enabled(),
        ),
        pystray.MenuItem("View Logs", _open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", quit_app),
    )
    icon = pystray.Icon("SwitchbladeReborn", _icon_image(), APP_NAME, menu)
    try:
        icon.run()
    finally:
        daemon.stop()
        worker.join(timeout=5.0)
        _release_single_instance(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
