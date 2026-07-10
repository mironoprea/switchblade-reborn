"""Tests for app.auto_switch - pure logic, no hardware needed."""

from unittest.mock import patch, MagicMock
from app.auto_switch import AutoSwitcher, get_foreground_exe


class TestAutoSwitcher:
    def test_init(self):
        switcher = AutoSwitcher({}, "default", on_switch=MagicMock())
        assert switcher._default == "default"

    def test_update_map(self):
        switcher = AutoSwitcher({}, "default", on_switch=MagicMock())
        switcher.update_map({"code.exe": "coding"}, "default")
        assert "code.exe" in switcher._map
        assert switcher._map["code.exe"] == "coding"

    def test_switches_to_mapped_profile(self):
        callback = MagicMock()
        switcher = AutoSwitcher({"code.exe": "coding"}, "default", on_switch=callback)

        with patch("app.auto_switch.get_foreground_exe", return_value="code.exe"):
            # Run one iteration
            switcher._stop = MagicMock()
            switcher._stop.is_set.side_effect = [False, True]
            switcher._stop.wait = MagicMock()
            switcher._run()

        callback.assert_called_once_with("coding")
        assert switcher._current_profile == "coding"

    def test_falls_back_to_default(self):
        callback = MagicMock()
        switcher = AutoSwitcher({"code.exe": "coding"}, "default", on_switch=callback)
        switcher._current_profile = "coding"

        with patch("app.auto_switch.get_foreground_exe", return_value="explorer.exe"):
            switcher._stop = MagicMock()
            switcher._stop.is_set.side_effect = [False, True]
            switcher._stop.wait = MagicMock()
            switcher._run()

        callback.assert_called_with("default")
        assert switcher._current_profile == "default"

    def test_no_switch_when_same_profile(self):
        callback = MagicMock()
        switcher = AutoSwitcher({"code.exe": "coding"}, "default", on_switch=callback)
        switcher._current_profile = "coding"

        with patch("app.auto_switch.get_foreground_exe", return_value="code.exe"):
            switcher._stop = MagicMock()
            switcher._stop.is_set.side_effect = [False, True]
            switcher._stop.wait = MagicMock()
            switcher._run()

        callback.assert_not_called()

    def test_handles_none_exe(self):
        callback = MagicMock()
        switcher = AutoSwitcher({"code.exe": "coding"}, "default", on_switch=callback)
        # Start from a non-default profile to verify fallback
        switcher._current_profile = "coding"

        with patch("app.auto_switch.get_foreground_exe", return_value=None):
            switcher._stop = MagicMock()
            switcher._stop.is_set.side_effect = [False, True]
            switcher._stop.wait = MagicMock()
            switcher._run()

        callback.assert_called_with("default")
        assert switcher._current_profile == "default"


class TestGetForegroundExe:
    def test_returns_none_on_non_windows(self):
        with patch("app.auto_switch.IS_WINDOWS", False):
            result = get_foreground_exe()
            assert result is None
