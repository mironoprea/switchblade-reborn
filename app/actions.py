"""
Execute user-configured actions from action dicts.

Action types:
  - launch:   subprocess.Popen, detached
  - keys:     keyboard shortcut injection via SendInput (pywin32 on Windows)
  - media:    media key injection (play/pause, next, prev, volume, mute)
  - profile:  switch active profile

On non-Windows platforms (or when pywin32 is unavailable), 'keys' and 'media'
fall back to logging — they need Windows SendInput to actually work.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    try:
        import win32con
        import win32api
        import win32gui
        import ctypes
        _HAS_WIN32 = True
    except ImportError:
        _HAS_WIN32 = False
        logger.warning(
            "pywin32 not available; 'keys' and 'media' actions will be no-ops."
        )
else:
    _HAS_WIN32 = False


# ---------------------------------------------------------------------------
# Media key virtual-key codes (Windows)
# ---------------------------------------------------------------------------

VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_VOLUME_UP = 0xAF
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_MUTE = 0xAD

MEDIA_VK_MAP = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "prev": VK_MEDIA_PREV_TRACK,
    "vol_up": VK_VOLUME_UP,
    "vol_down": VK_VOLUME_DOWN,
    "mute": VK_VOLUME_MUTE,
}

# ---------------------------------------------------------------------------
# Key name → virtual-key code map (subset; extended as needed)
# ---------------------------------------------------------------------------

KEY_VK_MAP: dict[str, int] = {}

if IS_WINDOWS and _HAS_WIN32:
    # Letters a-z
    for ch in range(ord("A"), ord("Z") + 1):
        KEY_VK_MAP[chr(ch).lower()] = ch
    # Digits 0-9
    for d in range(10):
        KEY_VK_MAP[str(d)] = ord("0") + d
    # Modifiers
    KEY_VK_MAP["ctrl"] = win32con.VK_CONTROL
    KEY_VK_MAP["alt"] = win32con.VK_MENU
    KEY_VK_MAP["shift"] = win32con.VK_SHIFT
    KEY_VK_MAP["win"] = win32con.VK_LWIN
    # Common keys
    KEY_VK_MAP["enter"] = win32con.VK_RETURN
    KEY_VK_MAP["return"] = win32con.VK_RETURN
    KEY_VK_MAP["tab"] = win32con.VK_TAB
    KEY_VK_MAP["esc"] = win32con.VK_ESCAPE
    KEY_VK_MAP["escape"] = win32con.VK_ESCAPE
    KEY_VK_MAP["space"] = win32con.VK_SPACE
    KEY_VK_MAP["backspace"] = win32con.VK_BACK
    KEY_VK_MAP["delete"] = win32con.VK_DELETE
    KEY_VK_MAP["home"] = win32con.VK_HOME
    KEY_VK_MAP["end"] = win32con.VK_END
    KEY_VK_MAP["up"] = win32con.VK_UP
    KEY_VK_MAP["down"] = win32con.VK_DOWN
    KEY_VK_MAP["left"] = win32con.VK_LEFT
    KEY_VK_MAP["right"] = win32con.VK_RIGHT
    # F1-F12
    for i in range(1, 13):
        KEY_VK_MAP[f"f{i}"] = win32con.VK_F1 + i - 1


# ---------------------------------------------------------------------------
# SendInput helpers (Windows)
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001


def _send_key_down_up(vk: int) -> None:
    """Press and release a single virtual key via SendInput."""
    if not (IS_WINDOWS and _HAS_WIN32):
        return

    user32 = ctypes.windll.user32

    # Key down
    extra = ctypes.c_ulong(0)
    # INPUT structure: type + ki (keyboard input)
    # We use the ctypes Structure approach for SendInput

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [
                ("ki", KEYBDINPUT),
                ("pad", ctypes.c_ubyte * 64),
            ]
        _anonymous_ = ("_input",)
        _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

    def make_input(vk_code: int, flags: int) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk_code
        inp.ki.wScan = 0
        inp.ki.dwFlags = flags
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(extra)
        return inp

    inputs = (INPUT * 2)(
        make_input(vk, 0),
        make_input(vk, KEYEVENTF_KEYUP),
    )
    user32.SendInput(2, ctypes.pointer(inputs[0]), ctypes.sizeof(INPUT))


def _send_combo(combo_str: str) -> None:
    """Send a key combination like 'ctrl+shift+m'."""
    parts = [p.strip().lower() for p in combo_str.split("+")]
    if not parts:
        return

    if not (IS_WINDOWS and _HAS_WIN32):
        logger.info("Would send keys: %s", combo_str)
        return

    user32 = ctypes.windll.user32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [
                ("ki", KEYBDINPUT),
                ("pad", ctypes.c_ubyte * 64),
            ]
        _anonymous_ = ("_input",)
        _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

    extra = ctypes.c_ulong(0)

    def make_input(vk_code: int, flags: int) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk_code
        inp.ki.wScan = 0
        inp.ki.dwFlags = flags
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(extra)
        return inp

    vks = []
    for p in parts:
        if p in KEY_VK_MAP:
            vks.append(KEY_VK_MAP[p])
        elif len(p) == 1 and p.isalpha():
            vks.append(ord(p.upper()))
        elif len(p) == 1 and p.isdigit():
            vks.append(ord(p))
        else:
            logger.warning("Unknown key in combo '%s': %s", combo_str, p)
            return

    inputs_list = []
    for vk in vks:
        inputs_list.append(make_input(vk, 0))
    for vk in reversed(vks):
        inputs_list.append(make_input(vk, KEYEVENTF_KEYUP))

    n = len(inputs_list)
    arr = (INPUT * n)(*inputs_list)
    user32.SendInput(n, ctypes.pointer(arr[0]), ctypes.sizeof(INPUT))


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def execute_action(
    action: dict,
    *,
    on_profile_switch: Optional[Callable[[str], None]] = None,
) -> None:
    """Execute a single action dict.  Dispatches by type."""
    atype = action.get("type")
    if atype is None:
        return

    logger.info("Executing action: %s", atype)

    if atype == "launch":
        _do_launch(action)
    elif atype == "keys":
        _do_keys(action)
    elif atype == "media":
        _do_media(action)
    elif atype == "profile":
        _do_profile_switch(action, on_profile_switch)
    else:
        logger.warning("Unknown action type: %s", atype)


def execute_action_async(
    action: dict,
    *,
    on_profile_switch: Optional[Callable[[str], None]] = None,
) -> threading.Thread:
    """Run ``execute_action`` in a worker thread, returning the thread."""
    t = threading.Thread(
        target=execute_action,
        args=(action,),
        kwargs={"on_profile_switch": on_profile_switch},
        daemon=True,
    )
    t.start()
    return t


def _do_launch(action: dict) -> None:
    path = action["path"]
    args = action.get("args", "")
    cmd = [path]
    if args:
        cmd += args.split()
    logger.info("Launching: %s", cmd)
    try:
        if IS_WINDOWS:
            # DETACHED_PROCESS on Windows
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0,
                close_fds=True,
            )
        else:
            subprocess.Popen(cmd, close_fds=True)
    except FileNotFoundError:
        logger.error("Launch failed — file not found: %s", path)
    except OSError as exc:
        logger.error("Launch failed: %s", exc)


def _do_keys(action: dict) -> None:
    sequence = action.get("sequence", [])
    for combo in sequence:
        _send_combo(combo)


def _do_media(action: dict) -> None:
    key = action.get("key")
    vk = MEDIA_VK_MAP.get(key)
    if vk is None:
        logger.warning("Unknown media key: %s", key)
        return
    _send_key_down_up(vk)


def _do_profile_switch(
    action: dict,
    on_profile_switch: Optional[Callable[[str], None]],
) -> None:
    name = action.get("name")
    if name is None:
        logger.warning("Profile switch action missing 'name'.")
        return
    if on_profile_switch is not None:
        on_profile_switch(name)
    else:
        logger.info("Profile switch requested to: %s", name)
