"""
Flask web UI for Switchblade Reborn.

Bound to 127.0.0.1:8377 only.  One page + JSON API.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from .. import profiles as profiles_mod

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROFILES_DIR = BASE_DIR / "profiles"
PROFILES_FILE = PROFILES_DIR / "profiles.json"
IMAGES_DIR = PROFILES_DIR / "images"


def create_app(daemon) -> Flask:
    """Create the Flask app, wired to the running daemon."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    @app.before_request
    def _guard_host():
        # The server binds to loopback only; reject any request whose Host isn't
        # loopback to block DNS-rebinding / cross-origin drive-by requests.
        host = request.host or ""
        hostname = host.rsplit(":", 1)[0]
        if hostname not in ("127.0.0.1", "localhost"):
            return jsonify({"ok": False, "error": "Forbidden host."}), 403

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status")
    def api_status():
        return jsonify(daemon.get_status())

    @app.route("/api/profiles", methods=["GET"])
    def get_profiles():
        return jsonify(daemon.profiles_data)

    @app.route("/api/profiles", methods=["PUT"])
    def put_profiles():
        data = request.get_json(force=True)
        try:
            profiles_mod.validate_profiles(data)
        except profiles_mod.ProfileError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        daemon.put_profiles(data)
        return jsonify({"ok": True})

    @app.route("/api/profiles/<name>/activate", methods=["POST"])
    def activate_profile(name):
        if daemon.switch_profile(name):
            return jsonify({"ok": True, "active_profile": name})
        return jsonify({"ok": False, "error": f"Profile '{name}' not found."}), 400

    @app.route("/api/upload-image", methods=["POST"])
    def upload_image():
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file provided."}), 400

        file = request.files["file"]

        # Size check (20 MB max)
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > 20 * 1024 * 1024:
            return jsonify({"ok": False, "error": "File too large (max 20 MB)."}), 400

        # Validate image via PIL
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(file.read()))
            img.verify()
            file.seek(0)
            img = Image.open(io.BytesIO(file.read()))
            img.load()
        except Exception:
            return jsonify({"ok": False, "error": "Invalid image file."}), 400

        # Re-encode to PNG and save.  secure_filename strips any path/traversal
        # components ('..\\..\\evil' -> 'evil') so a client can't write outside
        # IMAGES_DIR; the resolve() check below is defense in depth.
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        base = secure_filename(os.path.splitext(file.filename or "")[0]) or "upload"
        out_name = f"{base}.png"
        out_path = (IMAGES_DIR / out_name).resolve()
        if IMAGES_DIR.resolve() not in out_path.parents:
            return jsonify({"ok": False, "error": "Invalid filename."}), 400
        img.save(str(out_path), "PNG")

        return jsonify({
            "ok": True,
            "path": f"images/{out_name}",
            "url": f"/api/images/{out_name}",
        })

    @app.route("/api/images/<path:filename>")
    def serve_image(filename):
        return send_from_directory(str(IMAGES_DIR), filename)

    return app
