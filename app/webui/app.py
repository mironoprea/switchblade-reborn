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
    app.config["daemon"] = daemon

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
            daemon.profiles_data = data
            daemon.save_profiles()
            daemon.renderer.force_full_redraw()
            if daemon.link.is_ready():
                daemon._render_full_profile()
            return jsonify({"ok": True})
        except profiles_mod.ProfileError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/profiles/<name>/activate", methods=["POST"])
    def activate_profile(name):
        try:
            daemon.switch_profile(name)
            return jsonify({"ok": True, "active_profile": name})
        except profiles_mod.ProfileError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

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

        # Re-encode to PNG and save
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        filename = file.filename or "upload.png"
        base, _ = os.path.splitext(filename)
        out_name = f"{base}.png"
        out_path = IMAGES_DIR / out_name
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
