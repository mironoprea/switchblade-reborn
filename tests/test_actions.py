"""Tests for app.actions - pure logic, no hardware needed."""

import pytest
from unittest.mock import patch, MagicMock
from app import actions


class TestExecuteAction:
    def test_launch_action(self):
        action = {"type": "launch", "path": "C:/nonexistent/app.exe"}
        with patch("subprocess.Popen", side_effect=FileNotFoundError) as mock_popen:
            actions.execute_action(action)
            mock_popen.assert_called_once()

    def test_launch_action_with_args(self):
        action = {"type": "launch", "path": "C:/app.exe", "args": "--flag value"}
        with patch("subprocess.Popen") as mock_popen:
            actions.execute_action(action)
            call_args = mock_popen.call_args[0][0]
            assert "C:/app.exe" in call_args
            assert "--flag" in call_args
            assert "value" in call_args

    def test_keys_action(self):
        action = {"type": "keys", "sequence": ["ctrl+c"]}
        with patch.object(actions, "_send_combo") as mock_combo:
            actions.execute_action(action)
            mock_combo.assert_called_once_with("ctrl+c")

    def test_media_action(self):
        action = {"type": "media", "key": "play_pause"}
        with patch.object(actions, "_send_key_down_up") as mock_send:
            actions.execute_action(action)
            mock_send.assert_called_once()

    def test_media_action_unknown_key(self):
        action = {"type": "media", "key": "nonexistent"}
        with patch.object(actions, "_send_key_down_up") as mock_send:
            actions.execute_action(action)
            mock_send.assert_not_called()

    def test_profile_switch_action(self):
        action = {"type": "profile", "name": "gaming"}
        callback = MagicMock()
        actions.execute_action(action, on_profile_switch=callback)
        callback.assert_called_once_with("gaming")

    def test_profile_switch_no_callback(self):
        action = {"type": "profile", "name": "gaming"}
        actions.execute_action(action)

    def test_unknown_action_type(self):
        action = {"type": "explode"}
        actions.execute_action(action)

    def test_none_action_type(self):
        action = {}
        actions.execute_action(action)


class TestExecuteActionAsync:
    def test_runs_in_thread(self):
        action = {"type": "keys", "sequence": ["ctrl+c"]}
        with patch.object(actions, "_send_combo") as mock_combo:
            thread = actions.execute_action_async(action)
            thread.join(timeout=5.0)
            mock_combo.assert_called_once()

    def test_profile_switch_async(self):
        action = {"type": "profile", "name": "media"}
        callback = MagicMock()
        thread = actions.execute_action_async(action, on_profile_switch=callback)
        thread.join(timeout=5.0)
        callback.assert_called_once_with("media")


class TestKeyVkMap:
    def test_has_modifier_keys(self):
        assert "ctrl" in actions.KEY_VK_MAP
        assert "shift" in actions.KEY_VK_MAP
        assert "alt" in actions.KEY_VK_MAP
        assert "win" in actions.KEY_VK_MAP

    def test_has_media_keys(self):
        assert "play_pause" in actions.MEDIA_VK_MAP
        assert "next" in actions.MEDIA_VK_MAP
        assert "prev" in actions.MEDIA_VK_MAP
        assert "vol_up" in actions.MEDIA_VK_MAP
        assert "vol_down" in actions.MEDIA_VK_MAP
        assert "mute" in actions.MEDIA_VK_MAP
