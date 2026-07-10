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
    DISCONNECTED,
    INITIALIZING,
    READY,
    ERROR_FATAL,
)
from .widgets import render_widget_board
from .paths import profiles_dir, profiles_file
from .brightness import BrightnessController, BrightnessError

logger = logging.getLogger(__name__)

PROFILES_DIR = profiles_dir()
PROFILES_FILE = profiles_file()


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
        self.brightness = BrightnessController()
        self.renderer = ScreenRenderer()
        self.input_listener: Optional[InputListener] = None
        self._running = False
        self._initialized_device = False
        self._blank_key: Optional[bytes] = None
        self._current_profile_name: Optional[str] = None
        self._widget_timer = 0.0
        self._auto_switcher = None
        self._web_thread: Optional[threading.Thread] = None
        self._web_app = None
        self._web_server = None
        self._enable_web = web
        # Serializes all rendering: the main loop's widget refresh runs on the
        # main thread while profile switches arrive from the auto-switcher,
        # action-worker, and Flask threads.  Reentrant so nested render calls
        # (switch_profile -> _render_full_profile) don't self-deadlock.
        self._render_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start(self) -> None:
        # Load profiles
        try:
            self.profiles_data = profiles_mod.load_profiles(self.profiles_path)
        except profiles_mod.ProfileError as exc:
            logger.error("Profile error: %s", exc)
            sys.exit(1)

        self._current_profile_name = self.profiles_data.get("active_profile", "default")
        # Signal handlers for clean shutdown
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

        self._running = True

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
            from werkzeug.serving import make_server
            self._web_app = create_app(self)
            self._web_server = make_server("127.0.0.1", 8377, self._web_app, threaded=True)
            self._web_thread = threading.Thread(
                target=self._web_server.serve_forever,
                name="switchblade-web",
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
            logger.warning("Auto-switcher not started: %s", exc)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        while self._running:
            state = self.link.poll()

            if state == ERROR_FATAL:
                logger.error("Fatal error. Exiting.")
                break

            if state == INITIALIZING:
                self._initialize_device()
                self.link.mark_ready()

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
        with self._render_lock:
            self.renderer.force_full_redraw()
            self._render_full_profile()
            self._apply_brightness()

    def _apply_brightness(self) -> None:
        settings = self.profiles_data.get("settings", {})
        try:
            if "brightness" in settings:
                self.brightness.set_key_lcd_brightness(int(settings["brightness"]))
            if "keyboard_brightness" in settings:
                self.brightness.set_keyboard_brightness(int(settings["keyboard_brightness"]))
        except (BrightnessError, OSError, ValueError) as exc:
            logger.warning("Brightness control unavailable: %s", exc)

    def set_brightness(self, percent: int, *, target: str = "keys") -> None:
        if target == "keys":
            self.brightness.set_key_lcd_brightness(percent)
            self.profiles_data.setdefault("settings", {})["brightness"] = percent
        elif target == "keyboard":
            self.brightness.set_keyboard_brightness(percent)
            self.profiles_data.setdefault("settings", {})["keyboard_brightness"] = percent
        else:
            raise ValueError("target must be 'keys' or 'keyboard'")
        self.save_profiles()

    def _initialize_device(self) -> None:
        """Send the device init/mode-switch sequence, if any.

        [PORTED from FxChiP/rzswitchblade] No init sequence is needed - the
        reference C library claims the interface and blits immediately. This hook
        exists as a no-op placeholder. If hardware testing (with WinUSB bound
        instead of the Linux kernel driver detach path) reveals an init sequence
        is needed, fill it in here, e.g.:

            for packet in protocol.INIT_SEQUENCE:
                self.link.write(packet)
        """
        return

    def _render_full_profile(self) -> None:
        """Render the current profile's main screen."""
        with self._render_lock:
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
        """Render adaptive-key images when endpoint 0x02 is available."""
        if not self._key_images_supported():
            logger.debug("Skipping key-image blits; no key-image endpoint is available.")
            return
        profile = profiles_mod.get_active_profile(self.profiles_data)
        keys = profile.get("keys", [])
        for key_index in range(protocol.KEY_COUNT):
            key_config = keys[key_index] if key_index < len(keys) else None
            self._render_key(key_index, key_config)

    def _render_key(self, key_index: int, key_config: Optional[dict]) -> None:
        image_path = key_config.get("image") if key_config else None
        if image_path and os.path.isfile(self._resolve_path(image_path)):
            rgb565 = render_key_image_to_rgb565(self._resolve_path(image_path))
        else:
            # No image for this key: blit black so a previous profile's image
            # doesn't linger on the physical key after a switch.
            rgb565 = self._blank_key_image()
        self._blit_key(key_index, rgb565)

    def _blank_key_image(self) -> bytes:
        if self._blank_key is None:
            self._blank_key = render_solid_color(
                0, 0, 0,
                width=protocol.KEY_IMAGE_SIZE,
                height=protocol.KEY_IMAGE_SIZE,
            )
        return self._blank_key

    def _blit_rect(self, rect, payload: bytes) -> None:
        packet = protocol.build_blit(rect.x1, rect.y1, rect.x2, rect.y2, payload)
        try:
            self._write_blit_packet(packet)
        except ConnectionError as exc:
            logger.debug("Blit failed (device may have disconnected): %s", exc)

    def _blit_key(self, key_index: int, rgb565: bytes) -> None:
        packet = protocol.build_key_blit(key_index, rgb565)
        try:
            self._write_key_blit_packet(packet)
        except ConnectionError as exc:
            logger.debug("Key blit failed: %s", exc)

    def _write_blit_packet(self, packet: bytes) -> None:
        """Send a blit as header + one payload transfer.

        Hardware testing on the DeathStalker Ultimate confirms that chunking the
        pixel payload into 512-byte writes does not update the display reliably.
        The working form matches FxChiP/rzswitchblade: a 12-byte header transfer
        followed by the complete framebuffer/payload as one bulk transfer.
        """
        self.link.write_transfer(packet[:protocol.HEADER_SIZE])
        self.link.write_transfer(packet[protocol.HEADER_SIZE:])

    def _write_key_blit_packet(self, packet: bytes) -> None:
        """Send a key blit as header + one payload transfer to KEY_OUT."""
        self.link.write_key_transfer(packet[:protocol.HEADER_SIZE])
        self.link.write_key_transfer(packet[protocol.HEADER_SIZE:])

    def _key_images_supported(self) -> bool:
        """Return True when endpoint 0x02 can update the adaptive-key LCDs."""
        info = getattr(self.link, "info", None)
        return getattr(info, "key_out_endpoint", None) is not None

    def _refresh_widgets(self) -> None:
        with self._render_lock:
            profile = profiles_mod.get_active_profile(self.profiles_data)
            screen = profile.get("screen", {})
            if screen.get("type") != "widget_board":
                return
            img, _ = render_widget_board(screen)
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

    def switch_profile(self, name: str) -> bool:
        """Switch the active profile and re-render.

        Returns True on success, False if the profile doesn't exist.  Never
        raises — it's called from the auto-switcher and action-worker threads,
        which treat a bad name as a no-op.
        """
        with self._render_lock:
            try:
                profiles_mod.set_active_profile(self.profiles_data, name)
            except profiles_mod.ProfileError as exc:
                logger.error("Profile switch failed: %s", exc)
                return False
            self._current_profile_name = name
            self.profiles_data["active_profile"] = name
            logger.info("Switched to profile: %s", name)
            self.renderer.force_full_redraw()
            if self.link.is_ready():
                self._render_full_profile()
        return True

    def put_profiles(self, data: dict) -> None:
        """Replace all profile data (from the web UI) and re-render.

        Caller is responsible for validating ``data`` first.
        """
        with self._render_lock:
            self.profiles_data = data
            self._current_profile_name = data.get("active_profile")
            self._sync_auto_switcher()
            self.save_profiles()
            self.renderer.force_full_redraw()
            if self.link.is_ready():
                self._render_full_profile()

    def reload_profiles(self) -> None:
        """Reload profiles.json from disk."""
        try:
            data = profiles_mod.load_profiles(self.profiles_path)
        except profiles_mod.ProfileError as exc:
            logger.error("Profile reload failed: %s", exc)
            return
        with self._render_lock:
            self.profiles_data = data
            self._current_profile_name = data.get("active_profile", "default")
            self._sync_auto_switcher()
            self.renderer.force_full_redraw()
            if self.link.is_ready():
                self._render_full_profile()
        logger.info("Profiles reloaded.")

    def _sync_auto_switcher(self) -> None:
        """Push the current auto_switch map into the running switcher."""
        if self._auto_switcher is not None:
            self._auto_switcher.update_map(
                self.profiles_data.get("auto_switch", {}),
                self.profiles_data.get("active_profile", "default"),
            )

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
        self._write_blit_packet(packet)
        logger.info("Screen blit complete: %s", image_path)

    def blit_key(self, key_index: int, image_path: str) -> None:
        if not self.link.is_ready():
            logger.error("Device not ready.")
            return
        rgb565 = render_key_image_to_rgb565(image_path)
        packet = protocol.build_key_blit(key_index, rgb565)
        self._write_key_blit_packet(packet)
        logger.info("USB key blit complete: key=%d image=%s", key_index, image_path)

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
            "display_backend": "usb",
            "profiles_file": str(self.profiles_path),
            "device_error": self.link.last_error,
        }

    def stop(self) -> None:
        """Request a clean shutdown from the desktop/tray process."""
        self._running = False

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
        if self._web_server:
            self._web_server.shutdown()
            self._web_server = None
        # Web UI runs as daemon thread - it will be killed when the process exits
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
