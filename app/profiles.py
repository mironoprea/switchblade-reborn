"""
Profile management: load, validate, and save profiles.json.

Handles active-profile state.  Schema validation rejects malformed config
with a clear error message — never crashes.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .protocol import KEY_COUNT

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_ACTION_TYPES = {"launch", "keys", "media", "profile"}
VALID_MEDIA_KEYS = {
    "play_pause", "next", "prev", "vol_up", "vol_down", "mute",
}

CURRENT_VERSION = 1


class ProfileError(Exception):
    """Raised when profiles.json is invalid.  Message is user-friendly."""


def validate_profiles(data: Any) -> None:
    """Validate a parsed profiles dict.  Raises ``ProfileError`` on any issue."""
    if not isinstance(data, dict):
        raise ProfileError("Top-level must be a JSON object.")

    if "version" not in data:
        raise ProfileError("Missing 'version' field.")
    if not isinstance(data["version"], int):
        raise ProfileError("'version' must be an integer.")
    if data["version"] > CURRENT_VERSION:
        raise ProfileError(
            f"Profile version {data['version']} is newer than supported "
            f"({CURRENT_VERSION}). Please update Switchblade Reborn."
        )

    if "active_profile" not in data:
        raise ProfileError("Missing 'active_profile' field.")
    active = data["active_profile"]
    if not isinstance(active, str):
        raise ProfileError("'active_profile' must be a string.")

    if "profiles" not in data:
        raise ProfileError("Missing 'profiles' object.")
    profiles = data["profiles"]
    if not isinstance(profiles, dict):
        raise ProfileError("'profiles' must be a JSON object of profile-name -> profile.")

    if not profiles:
        raise ProfileError("'profiles' must contain at least one profile.")

    if active not in profiles:
        raise ProfileError(
            f"Active profile '{active}' not found in profiles. "
            f"Available: {', '.join(sorted(profiles))}"
        )

    # Settings (optional)
    settings = data.get("settings")
    if settings is not None:
        if not isinstance(settings, dict):
            raise ProfileError("'settings' must be a JSON object.")
        if "brightness" in settings:
            b = settings["brightness"]
            if not isinstance(b, int) or not (0 <= b <= 100):
                raise ProfileError("'brightness' must be an integer 0-100.")
        if "fps_cap" in settings:
            f = settings["fps_cap"]
            if not isinstance(f, int) or not (1 <= f <= 60):
                raise ProfileError("'fps_cap' must be an integer 1-60.")

    # Auto-switch (optional, Phase 4)
    auto_switch = data.get("auto_switch")
    if auto_switch is not None:
        if not isinstance(auto_switch, dict):
            raise ProfileError("'auto_switch' must be a JSON object of exe-name -> profile-name.")
        for exe, profile_name in auto_switch.items():
            if not isinstance(exe, str) or not isinstance(profile_name, str):
                raise ProfileError("'auto_switch' entries must be string -> string.")
            if profile_name not in profiles:
                raise ProfileError(
                    f"auto_switch references unknown profile '{profile_name}'."
                )

    # Validate each profile
    for name, profile in profiles.items():
        _validate_single_profile(name, profile, profiles)


def _validate_single_profile(name: str, profile: Any, all_profiles: dict) -> None:
    if not isinstance(profile, dict):
        raise ProfileError(f"Profile '{name}' must be a JSON object.")

    # Screen
    if "screen" not in profile:
        raise ProfileError(f"Profile '{name}' missing 'screen' object.")
    screen = profile["screen"]
    if not isinstance(screen, dict):
        raise ProfileError(f"Profile '{name}': 'screen' must be a JSON object.")

    stype = screen.get("type", "image")
    if stype not in ("image", "widget_board"):
        raise ProfileError(
            f"Profile '{name}': screen.type must be 'image' or 'widget_board', got {stype!r}."
        )

    if stype == "image":
        if "path" not in screen:
            raise ProfileError(f"Profile '{name}': screen with type 'image' needs 'path'.")
        if not isinstance(screen["path"], str):
            raise ProfileError(f"Profile '{name}': screen.path must be a string.")
    elif stype == "widget_board":
        widgets = screen.get("widgets")
        if widgets is not None:
            if not isinstance(widgets, list):
                raise ProfileError(
                    f"Profile '{name}': screen.widgets must be a list."
                )
            for i, w in enumerate(widgets):
                if not isinstance(w, dict):
                    raise ProfileError(f"Profile '{name}': widget {i} must be an object.")
                if "type" not in w:
                    raise ProfileError(f"Profile '{name}': widget {i} missing 'type'.")
                if w["type"] not in ("clock", "cpu_ram", "media_now_playing"):
                    raise ProfileError(
                        f"Profile '{name}': widget {i} has unknown type {w['type']!r}."
                    )

    # Keys
    if "keys" not in profile:
        raise ProfileError(f"Profile '{name}' missing 'keys' array.")
    keys = profile["keys"]
    if not isinstance(keys, list):
        raise ProfileError(f"Profile '{name}': 'keys' must be an array.")
    if len(keys) != KEY_COUNT:
        raise ProfileError(
            f"Profile '{name}': 'keys' must have exactly {KEY_COUNT} entries, "
            f"got {len(keys)}."
        )

    for i, key in enumerate(keys):
        if key is None:
            continue
        if not isinstance(key, dict):
            raise ProfileError(f"Profile '{name}': key {i} must be an object or null.")
        if "image" in key and key["image"] is not None:
            if not isinstance(key["image"], str):
                raise ProfileError(f"Profile '{name}': key {i} image must be a string or null.")
        if "label" in key and not isinstance(key["label"], str):
            raise ProfileError(f"Profile '{name}': key {i} label must be a string.")
        action = key.get("action")
        if action is not None:
            _validate_action(name, i, action, all_profiles)


def _validate_action(
    profile_name: str,
    key_index: int,
    action: Any,
    all_profiles: dict,
) -> None:
    if not isinstance(action, dict):
        raise ProfileError(
            f"Profile '{profile_name}': key {key_index} action must be an object."
        )
    if "type" not in action:
        raise ProfileError(
            f"Profile '{profile_name}': key {key_index} action missing 'type'."
        )
    atype = action["type"]
    if atype not in VALID_ACTION_TYPES:
        raise ProfileError(
            f"Profile '{profile_name}': key {key_index} action type {atype!r} "
            f"is invalid. Must be one of: {', '.join(sorted(VALID_ACTION_TYPES))}."
        )

    if atype == "launch":
        if "path" not in action or not isinstance(action["path"], str):
            raise ProfileError(
                f"Profile '{profile_name}': key {key_index} launch action needs 'path' (string)."
            )
    elif atype == "keys":
        seq = action.get("sequence")
        if not isinstance(seq, list) or not seq:
            raise ProfileError(
                f"Profile '{profile_name}': key {key_index} keys action needs "
                f"'sequence' (non-empty array of strings)."
            )
        for s in seq:
            if not isinstance(s, str):
                raise ProfileError(
                    f"Profile '{profile_name}': key {key_index} keys sequence "
                    f"items must be strings."
                )
    elif atype == "media":
        if "key" not in action or action["key"] not in VALID_MEDIA_KEYS:
            raise ProfileError(
                f"Profile '{profile_name}': key {key_index} media action needs "
                f"'key' in {sorted(VALID_MEDIA_KEYS)}."
            )
    elif atype == "profile":
        if "name" not in action or not isinstance(action["name"], str):
            raise ProfileError(
                f"Profile '{profile_name}': key {key_index} profile action needs 'name' (string)."
            )
        if action["name"] not in all_profiles:
            raise ProfileError(
                f"Profile '{profile_name}': key {key_index} references unknown "
                f"profile '{action['name']}'."
            )


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_profiles(path: str) -> dict:
    """Load and validate profiles.json.  Raises ``ProfileError`` on issues."""
    if not os.path.isfile(path):
        raise ProfileError(f"Profiles file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Invalid JSON in {path}: {exc}") from None
    validate_profiles(data)
    return data


def save_profiles(path: str, data: dict) -> None:
    """Validate then atomically write profiles.json.

    Writes to a temp file and ``os.replace``s it into place so a crash or power
    loss mid-write can't corrupt the user's only config copy.
    """
    validate_profiles(data)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def default_profiles() -> dict:
    """Return a default profiles dict."""
    return {
        "version": 1,
        "active_profile": "default",
        "settings": {"brightness": 80, "fps_cap": 15},
        "auto_switch": {},
        "profiles": {
            "default": {
                "screen": {"type": "image", "path": "images/bg.png"},
                "keys": [
                    {"image": None, "label": "", "action": None}
                    for _ in range(KEY_COUNT)
                ],
            }
        },
    }


def get_active_profile(data: dict) -> dict:
    """Return the active profile dict."""
    name = data["active_profile"]
    return data["profiles"][name]


def set_active_profile(data: dict, name: str) -> None:
    """Change the active profile in-place.  Validates before setting."""
    if name not in data["profiles"]:
        raise ProfileError(f"Profile '{name}' not found.")
    data["active_profile"] = name
