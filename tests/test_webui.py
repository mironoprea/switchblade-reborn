"""Tests for app.webui - Flask web UI, no hardware needed."""

import io
import pytest
from PIL import Image
from unittest.mock import MagicMock
from app.webui.app import create_app


def make_mock_daemon():
    daemon = MagicMock()
    daemon.profiles_data = {
        "version": 1,
        "active_profile": "default",
        "settings": {},
        "auto_switch": {},
        "profiles": {
            "default": {
                "screen": {"type": "image", "path": "images/bg.png"},
                "keys": [
                    {"image": None, "label": f"Key {i}", "action": None}
                    for i in range(10)
                ],
            },
            "media": {
                "screen": {"type": "image", "path": "images/bg.png"},
                "keys": [
                    {"image": None, "label": f"Key {i}", "action": None}
                    for i in range(10)
                ],
            },
        },
    }
    daemon.get_status.return_value = {
        "connection_state": "READY",
        "active_profile": "default",
        "profiles": ["default", "media"],
    }
    daemon.save_profiles.return_value = None
    daemon.put_profiles.return_value = None

    # Mirror the real Daemon.switch_profile contract: returns True on success,
    # False for an unknown profile (it never raises).
    def _switch_profile(name):
        return name in daemon.profiles_data["profiles"]
    daemon.switch_profile.side_effect = _switch_profile
    daemon.link.is_ready.return_value = False
    daemon.renderer.force_full_redraw.return_value = None
    return daemon


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Redirect uploads into a temp dir so tests never write into the repo tree.
    import app.webui.app as webui_app
    monkeypatch.setattr(webui_app, "IMAGES_DIR", tmp_path / "images")
    daemon = make_mock_daemon()
    app = create_app(daemon)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestStatusEndpoint:
    def test_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "connection_state" in data
        assert "active_profile" in data
        assert "profiles" in data


class TestProfilesEndpoint:
    def test_get_profiles(self, client):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "version" in data
        assert "profiles" in data

    def test_put_profiles_valid(self, client):
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
        resp = client.put("/api/profiles", json=data)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_put_profiles_invalid(self, client):
        data = {"version": 1}
        resp = client.put("/api/profiles", json=data)
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False


class TestActivateProfile:
    def test_activate_existing(self, client):
        resp = client.post("/api/profiles/media/activate")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_activate_nonexistent(self, client):
        resp = client.post("/api/profiles/nonexistent/activate")
        assert resp.status_code == 400


class TestUploadImage:
    def test_upload_valid_png(self, client):
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        resp = client.post(
            "/api/upload-image",
            data={"file": (buf, "test.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "path" in data

    def test_upload_invalid_file(self, client):
        resp = client.post(
            "/api/upload-image",
            data={"file": (io.BytesIO(b"not an image"), "bad.txt")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False

    def test_upload_no_file(self, client):
        resp = client.post("/api/upload-image", content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_rejects_path_traversal(self, client, tmp_path):
        img = Image.new("RGB", (10, 10), (0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        resp = client.post(
            "/api/upload-image",
            data={"file": (buf, "../../../../evil.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # The traversal is sanitized away, so nothing escapes the images dir.
        assert ".." not in data["path"]
        assert not (tmp_path.parent / "evil.png").exists()


class TestIndexPage:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Switchblade" in resp.data


class TestHostGuard:
    def test_rejects_foreign_host(self, client):
        resp = client.get("/api/status", headers={"Host": "evil.example.com"})
        assert resp.status_code == 403

    def test_allows_loopback_host(self, client):
        resp = client.get("/api/status", headers={"Host": "127.0.0.1:8377"})
        assert resp.status_code == 200
