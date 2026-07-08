"""
Daemon: wires all modules together, runs the main loop and state machine.

Connection state machine:

  DISCONNECTED --device found--> CLAIMING --claim ok--> INITIALIZING
  INITIALIZING --init sent, test blit ok--> READY
  READY --usb error / unplug--> DISCONNECTED (release handle, retry every 2 s)
  CLAIMING --claim fails--> ERROR_FATAL
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from . import protocol
from . import profiles as profiles_mod
from .actions import execute_action_async
from .input_listener import InputListener
from .renderer import (
    ScreenRenderer,
    render_image_to_framebuffer,
    render_key_image_to_rgb565,
    render_solid_color,
    image_to_rgb565_fast,
)
from .usb_link import (
    UsbLink,
    is_synapse_running,
    DISCONNECTED,
    READY,
    ERROR_FATAL,
)
from .widgets import render_widget_board

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "profiles"
PROFILES_FILE = PROFILES_DIR / "profiles.json"
IMAGES_DIR = PROFILES_DIR / "images"


class Daemon:
    """The main daemon process."""

    def __init__(
        self,
        profiles_path: Optional[str] = None,
        *,
        interface: Optional[int] = None,
        web: bool = True,
    ) -> None:
        self.profiles_path = profiles_path or str(PROFILES_FILE)
        self.profiles_data: dict = {}
        self.link = UsbLink(interface=interface)
        self.renderer = ScreenRenderer()
        self.input_listener: Optional[InputListener] = None
        self._running = False
        self._key_images: dict[int, bytes] = {}
        self._current_profile_name: Optional[str] = None
        self._widget_timer = 0.0
        self._auto_switcher = None
        self._web_thread: Optional[threading.Thread] = None
        self._web_app = None
        self._enable_web = web

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start(self) -> None:
        # Synapse guard
        if is_synapse_running():
            logger.error(
                "Razer Synapse appears to be running. Please fully exit Synapse "
                "(tray → Exit, kill Rz* processes) before starting Switchblade Reborn."
            )
            sys.exit(1)

        # Load profiles
        try:
            self.profiles_data = profiles_mod.load_profiles(self.profiles_path)
        except profiles_mod.ProfileError as exc:
            logger.error("Profile error: %s", exc)
            sys.exit(1)

        self._current_profile_name = self.profiles_data.get("active_profile", "default")

        # Signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running = True
        self._initialized_device = False

        # Start web UI
        if self._enable_web:
            self._start_web()

        # Start input listener
        self.input_listener = InputListener(self.link, self._on_key_event)
        self.input_listener.start()

        # Start auto-switcher
        self._start_auto_switcher()

        logger.info("Daemon started. Active profile: %s", self._current_profile_name)
        self._main_loop()

    def _start_web(self) -> None:
        try:
            from .webui.app import create_app
            self._web_app = create_app(self)
            self._web_thread = threading.Thread(
                target=self._web_app.run,
                kwargs={
                    "host": "127.0.0.1",
                    "port": 8377,
                    "debug": False,
                    "use_reloader": False,
                },
                daemon=True,
            )
            self._web_thread.start()
            logger.info("Web UI started at http://127.0.0.1:8377")
        except ImportError:
            logger.warning("Flask not available; web UI disabled.")
        except Exception as exc:
            logger.warning("Web UI failed to start: %s", exc)

    def _start_auto_switcher(self) -> None:
        try:
            from .auto_switch import AutoSwitcher
            auto_map = self.profiles_data.get("auto_switch", {})
            default = self.profiles_data.get("active_profile", "default")
            self._auto_switcher = AutoSwitcher(
                auto_map, default, on_switch=self.switch_profile
            )
            self._auto_switcher.start()
        except Exception as exc:
            logger.debug("Auto-switcher not started: %s", exc)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        while self._running:
            state = self.link.poll()

            if state == ERROR_FATAL:
                logger.error("Fatal error. Exiting.")
                break

            if state == READY and not self._initialized_device:
                self._on_device_ready()
                self._initialized_device = True

            if state == DISCONNECTED:
                self._initialized_device = False

            # Widget refresh at ~1 Hz
            if self.link.is_ready():
                now = time.time()
                if now - self._widget_timer >= 1.0:
                    self._widget_timer = now
                    self._refresh_widgets()

            # FPS cap: sleep according to settings (default 15 fps)
            settings = self.profiles_data.get("settings", {})
            fps_cap = settings.get("fps_cap", 15)
            sleep_time = max(1.0 / fps_cap, 0.01)
            time.sleep(sleep_time)

        self._shutdown()

    def _on_device_ready(self) -> None:
        """Called when the device enters READY state for the first time."""
        logger.info("Device ready. Rendering active profile.")
        self.renderer.force_full_redraw()
        self._render_full_profile()

    def _render_full_profile(self) -> None:
        """Render screen + all key images for the current profile."""
        self._render_screen()
        self._render_all_keys()

    def _render_screen(self) -> None:
        profile = profiles_mod.get_active_profile(self.profiles_data)
        screen = profile.get("screen", {})
        stype = screen.get("type", "image")

        if stype == "image":
            path = screen.get("path")
            if path and os.path.isfile(self._resolve_path(path)):
                fb = render_image_to_framebuffer(self._resolve_path(path))
            else:
                fb = render_solid_color(10, 10, 40)
        elif stype == "widget_board":
            img, _ = render_widget_board(screen)
            fb = image_to_rgb565_fast(img)
        else:
            fb = render_solid_color(0, 0, 0)

        result = self.renderer.update(fb)
        if result is not None:
            rect, payload = result
            self._blit_rect(rect, payload)

    def _render_all_keys(self) -> None:
        profile = profiles_mod.get_active_profile(self.profiles_data)
        keys = profile.get("keys", [])
        for i in range(protocol.KEY_COUNT):
            self._render_key(i, keys[i] if i < len(keys) else None)

    def _render_key(self, key_index: int, key_config: Optional[dict]) -> None:
        if key_config is None:
            return
        image_path = key_config.get("image")
        if image_path and os.path.isfile(self._resolve_path(image_path)):
            rgb565 = render_key_image_to_rgb565(self._resolve_path(image_path))
            self._blit_key(key_index, rgb565)

    def _blit_rect(self, rect, payload: bytes) -> None:
        packet = protocol.build_blit(rect.x1, rect.y1, rect.x2, rect.y2, payload)
        try:
            self.link.write(packet)
        except ConnectionError as exc:
            logger.debug("Blit failed (device may have disconnected): %s", exc)

    def _blit_key(self, key_index: int, rgb565: bytes) -> None:
        packet = protocol.build_key_blit(key_index, rgb565)
        try:
            self.link.write(packet)
        except ConnectionError as exc:
            logger.debug("Key blit failed: %s", exc)

    def _refresh_widgets(self) -> None:
        profile = profiles_mod.get_active_profile(self.profiles_data)
        screen = profile.get("screen", {})
        if screen.get("type") != "widget_board":
            return
        img, dirty_rects = render_widget_board(screen)
        fb = image_to_rgb565_fast(img)
        result = self.renderer.update(fb)
        if result is not None:
            rect, payload = result
            self._blit_rect(rect, payload)

    # ------------------------------------------------------------------
    # Key event handling
    # ------------------------------------------------------------------

    def _on_key_event(self, event: protocol.KeyEvent) -> None:
        if not event.pressed:
            return
        profile = profiles_mod.get_active_profile(self.profiles_data)
        keys = profile.get("keys", [])
        if event.key_index >= len(keys):
            return
        key = keys[event.key_index]
        if key is None:
            return
        action = key.get("action")
        if action is None:
            return
        execute_action_async(action, on_profile_switch=self.switch_profile)

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def switch_profile(self, name: str) -> None:
        """Switch the active profile and re-render."""
        try:
            profiles_mod.set_active_profile(self.profiles_data, name)
        except profiles_mod.ProfileError as exc:
            logger.error("Profile switch failed: %s", exc)
            return
        self._current_profile_name = name
        self.profiles_data["active_profile"] = name
        logger.info("Switched to profile: %s", name)
        self.renderer.force_full_redraw()
        if self.link.is_ready():
            self._render_full_profile()

    def reload_profiles(self) -> None:
        """Reload profiles.json from disk."""
        try:
            self.profiles_data = profiles_mod.load_profiles(self.profiles_path)
            self._current_profile_name = self.profiles_data.get("active_profile", "default")
            self.renderer.force_full_redraw()
            if self.link.is_ready():
                self._render_full_profile()
            logger.info("Profiles reloaded.")
        except profiles_mod.ProfileError as exc:
            logger.error("Profile reload failed: %s", exc)

    def save_profiles(self) -> None:
        """Persist current profiles to disk."""
        try:
            profiles_mod.save_profiles(self.profiles_path, self.profiles_data)
        except profiles_mod.ProfileError as exc:
            logger.error("Profile save failed: %s", exc)

    # ------------------------------------------------------------------
    # Blit commands (used by CLI)
    # ------------------------------------------------------------------

    def blit_screen(self, image_path: str) -> None:
        if not self.link.is_ready():
            logger.error("Device not ready.")
            return
        fb = render_image_to_framebuffer(image_path)
        packet = protocol.build_screen_blit(fb)
        self.link.write(packet)
        logger.info("Screen blit complete: %s", image_path)

    def blit_key(self, key_index: int, image_path: str) -> None:
        if not self.link.is_ready():
            logger.error("Device not ready.")
            return
        rgb565 = render_key_image_to_rgb565(image_path)
        packet = protocol.build_key_blit(key_index, rgb565)
        self.link.write(packet)
        logger.info("Key %d blit complete: %s", key_index, image_path)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> str:
        """Resolve a profile-relative path to an absolute path."""
        if os.path.isabs(path):
            return path
        return str(PROFILES_DIR / path)

    def get_status(self) -> dict:
        return {
            "connection_state": self.link.state,
            "active_profile": self._current_profile_name,
            "profiles": list(self.profiles_data.get("profiles", {}).keys()),
        }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _signal_handler(self, signum, frame) -> None:
        logger.info("Signal %d received, shutting down...", signum)
        self._running = False

    def _shutdown(self) -> None:
        logger.info("Shutting down...")
        if self.input_listener:
            self.input_listener.stop()
        if self._auto_switcher:
            self._auto_switcher.stop()
        if self._web_app:
            try:
                # Signal Flask to shut down
                func = self._web_app.view_functions.get("shutdown", None)
                if func:
                    func()
            except Exception:
                pass
        self.link.disconnect()
        logger.info("Shutdown complete.")


def run_daemon(
    profiles_path: Optional[str] = None,
    *,
    interface: Optional[int] = None,
    web: bool = True,
) -> None:
    """Entry point: create and start the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    daemon = Daemon(profiles_path, interface=interface, web=web)
    daemon.start()
