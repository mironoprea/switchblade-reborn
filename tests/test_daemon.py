"""Tests for app.daemon - integration, no hardware needed."""

import json
import os
import tempfile
import pytest
from app.daemon import Daemon
from app.profiles import ProfileError


class TestDaemonInit:
    def test_daemon_initializes(self):
        daemon = Daemon(web=False)
        assert daemon.profiles_data == {}
        assert daemon._current_profile_name is None
        assert daemon._running is False

    def test_daemon_with_custom_profiles(self):
        data = {
            "version": 1,
            "active_profile": "default",
            "settings": {"brightness": 80, "fps_cap": 15},
            "auto_switch": {},
            "profiles": {
                "default": {
                    "screen": {"type": "image", "path": "images/bg.png"},
                    "keys": [
                        {"image": None, "label": "", "action": None}
                        for _ in range(10)
                    ],
                }
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            daemon = Daemon(path, web=False)
            assert daemon.profiles_path == path
        finally:
            os.unlink(path)

    def test_get_status_no_profiles(self):
        daemon = Daemon(web=False)
        status = daemon.get_status()
        assert "connection_state" in status
        assert "active_profile" in status
        assert "profiles" in status

    def test_resolve_path_relative(self):
        daemon = Daemon(web=False)
        resolved = daemon._resolve_path("images/bg.png")
        assert os.path.isabs(resolved)
        assert "images" in resolved

    def test_resolve_path_absolute(self):
        daemon = Daemon(web=False)
        abs_path = os.path.abspath("/some/path/image.png")
        resolved = daemon._resolve_path(abs_path)
        assert resolved == abs_path

    def test_switch_profile_nonexistent(self):
        daemon = Daemon(web=False)
        daemon.profiles_data = {
            "version": 1,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "screen": {"type": "image", "path": "images/bg.png"},
                    "keys": [
                        {"image": None, "label": "", "action": None}
                        for _ in range(10)
                    ],
                }
            },
        }
        # Should not crash, just log error
        daemon.switch_profile("nonexistent")
        assert daemon._current_profile_name != "nonexistent"

    def test_switch_profile_valid(self):
        daemon = Daemon(web=False)
        daemon.profiles_data = {
            "version": 1,
            "active_profile": "default",
            "settings": {},
            "auto_switch": {},
            "profiles": {
                "default": {
                    "screen": {"type": "image", "path": "images/bg.png"},
                    "keys": [
                        {"image": None, "label": "", "action": None}
                        for _ in range(10)
                    ],
                },
                "media": {
                    "screen": {"type": "image", "path": "images/bg.png"},
                    "keys": [
                        {"image": None, "label": "", "action": None}
                        for _ in range(10)
                    ],
                },
            },
        }
        daemon.switch_profile("media")
        assert daemon._current_profile_name == "media"
        assert daemon.profiles_data["active_profile"] == "media"

    def test_render_full_profile_does_not_blit_key_images(self, monkeypatch):
        daemon = Daemon(web=False)
        daemon.profiles_data = {
            "version": 1,
            "active_profile": "default",
            "settings": {},
            "auto_switch": {},
            "profiles": {
                "default": {
                    "screen": {"type": "image", "path": "missing.png"},
                    "keys": [
                        {"image": "images/key0.png", "label": "Key 0", "action": None}
                    ],
                }
            },
        }

        key_blits = []
        monkeypatch.setattr(daemon, "_blit_key", lambda *args: key_blits.append(args))

        daemon._render_full_profile()

        assert key_blits == []
