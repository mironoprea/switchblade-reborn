"""Filesystem locations for development and installed builds.

Source checkouts keep using the repository's ``profiles`` directory so existing
developer workflows remain unchanged.  Frozen Windows builds copy bundled
defaults into a writable per-user directory on first launch.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Switchblade Reborn"
APP_DIR_NAME = "SwitchbladeReborn"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Return the read-only directory containing bundled application files."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Return the writable application data directory."""
    override = os.environ.get("SWITCHBLADE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    return resource_root()


def profiles_dir() -> Path:
    return data_root() / "profiles"


def profiles_file() -> Path:
    return profiles_dir() / "profiles.json"


def images_dir() -> Path:
    return profiles_dir() / "images"


def logs_dir() -> Path:
    return data_root() / "logs"


def log_file() -> Path:
    return logs_dir() / "switchblade-reborn.log"


def bootstrap_user_data() -> Path:
    """Create writable settings and copy bundled defaults on first launch."""
    destination = profiles_dir()
    destination.mkdir(parents=True, exist_ok=True)
    images_dir().mkdir(parents=True, exist_ok=True)

    source = resource_root() / "profiles"
    target_config = profiles_file()
    if not target_config.exists() and (source / "profiles.json").is_file():
        shutil.copy2(source / "profiles.json", target_config)

    source_images = source / "images"
    if source_images.is_dir():
        for item in source_images.iterdir():
            if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                target = images_dir() / item.name
                if not target.exists():
                    shutil.copy2(item, target)

    return target_config
