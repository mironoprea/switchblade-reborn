"""
Execute user-configured actions from action dicts.

Action types:
  - launch:   subprocess.Popen, detached
  - keys:     keyboard shortcut injection via SendInput (pywin32 on Windows)
  - media:    media key injection (play/pause, next, prev, volume, mute)
  - profile:  switch active profile

On non-Windows platforms, 'keys' and 'media' fall back to logging — they need
Windows SendInput to actually work.  Key injection uses stdlib ``ctypes`` only
(no pywin32 dependency).
"""

from __future__ import annotations

import ctypes
import logging
import platform
import subprocess
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

IS_WINDOWS = platform.system() == "Windows"


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

# Virtual-key codes are just constants; define them on all platforms
# so the map is usable for validation and testing without Windows.
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_BACK = 0x08
VK_DELETE = 0x2E
VK_HOME = 0x24
VK_END = 0x23
VK_UP = 0x26
VK_DOWN = 0x28
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_F1 = 0x70

KEY_VK_MAP: dict[str, int] = {}

# Letters a-z
for ch in range(ord("A"), ord("Z") + 1):
    KEY_VK_MAP[chr(ch).lower()] = ch
# Digits 0-9
for d in range(10):
    KEY_VK_MAP[str(d)] = ord("0") + d
# Modifiers
KEY_VK_MAP["ctrl"] = VK_CONTROL
KEY_VK_MAP["alt"] = VK_MENU
KEY_VK_MAP["shift"] = VK_SHIFT
KEY_VK_MAP["win"] = VK_LWIN
# Common keys
KEY_VK_MAP["enter"] = VK_RETURN
KEY_VK_MAP["return"] = VK_RETURN
KEY_VK_MAP["tab"] = VK_TAB
KEY_VK_MAP["esc"] = VK_ESCAPE
KEY_VK_MAP["escape"] = VK_ESCAPE
KEY_VK_MAP["space"] = VK_SPACE
KEY_VK_MAP["backspace"] = VK_BACK
KEY_VK_MAP["delete"] = VK_DELETE
KEY_VK_MAP["home"] = VK_HOME
KEY_VK_MAP["end"] = VK_END
KEY_VK_MAP["up"] = VK_UP
KEY_VK_MAP["down"] = VK_DOWN
KEY_VK_MAP["left"] = VK_LEFT
KEY_VK_MAP["right"] = VK_RIGHT
# F1-F12
for i in range(1, 13):
    KEY_VK_MAP[f"f{i}"] = VK_F1 + i - 1


# ---------------------------------------------------------------------------
# SendInput structures (Win32) — canonical layout
# ---------------------------------------------------------------------------
#
# ``INPUT`` is 40 bytes on x64 / 28 bytes on x86.  SendInput rejects the call
# (returns 0, injects nothing) when ``cbSize`` doesn't match the OS's expected
# size, so the union MUST size itself via the real member structs — no padding.

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

# ULONG_PTR — pointer-sized unsigned integer (the correct type for dwExtraInfo).
ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    # Present only so the union sizes to the largest member (as the OS expects).
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("u", _INPUTUNION),
    ]


# Virtual keys on the "extended" region of the keyboard; these need
# KEYEVENTF_EXTENDEDKEY set for reliable injection.
_EXTENDED_VKS = frozenset({
    VK_DELETE, VK_HOME, VK_END, VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT,
})


# Load user32 with last-error capture so SendInput failures can be diagnosed.
if IS_WINDOWS:
    try:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.SendInput.argtypes = (
            ctypes.c_uint,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        )
        _user32.SendInput.restype = ctypes.c_uint
        _HAS_WIN32 = True
    except (OSError, AttributeError) as exc:  # pragma: no cover - Windows only
        _user32 = None
        _HAS_WIN32 = False
        logger.warning("user32.SendInput unavailable; 'keys'/'media' are no-ops: %s", exc)
else:
    _user32 = None
    _HAS_WIN32 = False


def _make_key_input(vk: int, flags: int) -> INPUT:
    if vk in _EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = 0
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = 0
    return inp


def _send_inputs(inputs: list) -> None:
    """Inject a sequence of INPUT events, logging any partial/failed send."""
    n = len(inputs)
    if n == 0 or _user32 is None:
        return
    arr = (INPUT * n)(*inputs)
    sent = _user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        err = ctypes.get_last_error()
        logger.error("SendInput injected %d of %d events (last error %d).", sent, n, err)


def _send_key_down_up(vk: int) -> None:
    """Press and release a single virtual key via SendInput."""
    if not (IS_WINDOWS and _HAS_WIN32):
        return
    _send_inputs([
        _make_key_input(vk, 0),
        _make_key_input(vk, KEYEVENTF_KEYUP),
    ])


def _send_combo(combo_str: str) -> None:
    """Send a key combination like 'ctrl+shift+m'."""
    parts = [p.strip().lower() for p in combo_str.split("+")]
    if not parts:
        return

    if not (IS_WINDOWS and _HAS_WIN32):
        logger.info("Would send keys: %s", combo_str)
        return

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

    inputs = [_make_key_input(vk, 0) for vk in vks]
    inputs += [_make_key_input(vk, KEYEVENTF_KEYUP) for vk in reversed(vks)]
    _send_inputs(inputs)


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
