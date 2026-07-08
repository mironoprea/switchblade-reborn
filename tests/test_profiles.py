"""Tests for app.profiles — schema validation."""

import copy
import json
import os
import tempfile
import pytest
from app import profiles


def make_good_profile():
    return {
        "version": 1,
        "active_profile": "default",
        "settings": {"brightness": 80, "fps_cap": 15},
        "profiles": {
            "default": {
                "screen": {"type": "image", "path": "images/bg.png"},
                "keys": [
                    {"image": "images/k0.png", "label": "K0",
                     "action": {"type": "launch", "path": "C:/app.exe"}},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                    {"image": None, "label": "", "action": None},
                ]
            }
        }
    }


class TestValidProfiles:
    def test_good_profile_validates(self):
        profiles.validate_profiles(make_good_profile())

    def test_good_profile_with_all_action_types(self):
        data = make_good_profile()
        data["profiles"]["default"]["keys"][1]["action"] = {"type": "keys", "sequence": ["ctrl+c"]}
        data["profiles"]["default"]["keys"][2]["action"] = {"type": "media", "key": "play_pause"}
        data["profiles"]["default"]["keys"][3]["action"] = {"type": "profile", "name": "default"}
        profiles.validate_profiles(data)

    def test_widget_board_screen(self):
        data = make_good_profile()
        data["profiles"]["default"]["screen"] = {
            "type": "widget_board",
            "widgets": [
                {"type": "clock", "x": 10, "y": 10},
                {"type": "cpu_ram", "x": 10, "y": 50},
            ]
        }
        profiles.validate_profiles(data)

    def test_auto_switch(self):
        data = make_good_profile()
        data["auto_switch"] = {"code.exe": "default"}
        profiles.validate_profiles(data)


class TestInvalidProfiles:
    def test_missing_version(self):
        data = make_good_profile()
        del data["version"]
        with pytest.raises(profiles.ProfileError, match="version"):
            profiles.validate_profiles(data)

    def test_missing_active_profile(self):
        data = make_good_profile()
        del data["active_profile"]
        with pytest.raises(profiles.ProfileError, match="active_profile"):
            profiles.validate_profiles(data)

    def test_active_profile_not_found(self):
        data = make_good_profile()
        data["active_profile"] = "nonexistent"
        with pytest.raises(profiles.ProfileError, match="not found"):
            profiles.validate_profiles(data)

    def test_wrong_key_count(self):
        data = make_good_profile()
        data["profiles"]["default"]["keys"].pop()
        with pytest.raises(profiles.ProfileError, match="10"):
            profiles.validate_profiles(data)

    def test_invalid_action_type(self):
        data = make_good_profile()
        data["profiles"]["default"]["keys"][0]["action"] = {"type": "explode"}
        with pytest.raises(profiles.ProfileError, match="invalid"):
            profiles.validate_profiles(data)

    def test_launch_missing_path(self):
        data = make_good_profile()
        data["profiles"]["default"]["keys"][0]["action"] = {"type": "launch"}
        with pytest.raises(profiles.ProfileError, match="path"):
            profiles.validate_profiles(data)

    def test_media_invalid_key(self):
        data = make_good_profile()
        data["profiles"]["default"]["keys"][0]["action"] = {"type": "media", "key": "explode"}
        with pytest.raises(profiles.ProfileError, match="media"):
            profiles.validate_profiles(data)

    def test_profile_switch_unknown_profile(self):
        data = make_good_profile()
        data["profiles"]["default"]["keys"][0]["action"] = {"type": "profile", "name": "ghost"}
        with pytest.raises(profiles.ProfileError, match="unknown"):
            profiles.validate_profiles(data)

    def test_brightness_out_of_range(self):
        data = make_good_profile()
        data["settings"]["brightness"] = 150
        with pytest.raises(profiles.ProfileError, match="brightness"):
            profiles.validate_profiles(data)


class TestLoadSave:
    def test_load_valid_file(self):
        data = make_good_profile()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        loaded = profiles.load_profiles(path)
        assert loaded["active_profile"] == "default"
        os.unlink(path)

    def test_load_nonexistent(self):
        with pytest.raises(profiles.ProfileError, match="not found"):
            profiles.load_profiles("/nonexistent/path/file.json")

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            path = f.name
        with pytest.raises(profiles.ProfileError, match="Invalid JSON"):
            profiles.load_profiles(path)
        os.unlink(path)

    def test_save_and_reload(self):
        data = make_good_profile()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            path = f.name
        profiles.save_profiles(path, data)
        loaded = profiles.load_profiles(path)
        assert loaded == data
        os.unlink(path)


class TestActiveProfile:
    def test_get_active_profile(self):
        data = make_good_profile()
        active = profiles.get_active_profile(data)
        assert active["screen"]["type"] == "image"

    def test_set_active_profile(self):
        data = make_good_profile()
        data["profiles"]["second"] = copy.deepcopy(data["profiles"]["default"])
        profiles.set_active_profile(data, "second")
        assert data["active_profile"] == "second"

    def test_set_active_profile_invalid(self):
        data = make_good_profile()
        with pytest.raises(profiles.ProfileError, match="not found"):
            profiles.set_active_profile(data, "ghost")
