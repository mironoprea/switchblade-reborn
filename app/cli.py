"""
Command-line interface: `python -m app.cli <command>`

Commands:
  run                Start the daemon
  profile <name>    Switch active profile (writes profiles.json; takes effect on daemon restart)
  blit-screen <img>  Blit an image to the trackpad screen
  blit-key <N> <img> Blit an image to adaptive key N (0-9)
  validate           Validate profiles.json
  status             Show connection state and active profile
  install-autostart  Install Windows Task Scheduler autostart entry
  uninstall-autostart  Remove the autostart entry
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import profiles as profiles_mod
from .paths import bootstrap_user_data, profiles_file, resource_root

BASE_DIR = resource_root()
PROFILES_FILE = profiles_file()


def main() -> int:
    bootstrap_user_data()
    parser = argparse.ArgumentParser(
        prog="app.cli",
        description="Switchblade Reborn — control app for Razer DeathStalker Ultimate",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Start the daemon")
    p_run.add_argument("--profiles", default=str(PROFILES_FILE))
    p_run.add_argument("--interface", type=int, default=None)
    p_run.add_argument("--no-web", action="store_true")

    # profile
    p_profile = sub.add_parser("profile", help="Switch active profile")
    p_profile.add_argument("name")
    p_profile.add_argument("--profiles", default=str(PROFILES_FILE))

    # blit-screen
    p_blit_screen = sub.add_parser("blit-screen", help="Blit image to trackpad screen")
    p_blit_screen.add_argument("image")
    p_blit_screen.add_argument("--profiles", default=str(PROFILES_FILE))
    p_blit_screen.add_argument("--interface", type=int, default=None)

    # blit-key
    p_blit_key = sub.add_parser("blit-key", help="Blit image to adaptive key N (0-9)")
    p_blit_key.add_argument("key", type=int)
    p_blit_key.add_argument("image")
    p_blit_key.add_argument("--profiles", default=str(PROFILES_FILE))
    p_blit_key.add_argument("--interface", type=int, default=None)

    # validate
    p_validate = sub.add_parser("validate", help="Validate profiles.json")
    p_validate.add_argument("--profiles", default=str(PROFILES_FILE))

    # status
    p_status = sub.add_parser("status", help="Show status")
    p_status.add_argument("--profiles", default=str(PROFILES_FILE))

    p_brightness = sub.add_parser("brightness", help="Set adaptive-key or keyboard brightness")
    p_brightness.add_argument("percent", type=int)
    p_brightness.add_argument("--target", choices=["keys", "keyboard"], default="keys")
    p_brightness.add_argument("--profiles", default=str(PROFILES_FILE))

    # install-autostart
    sub.add_parser("install-autostart", help="Install Windows autostart task")
    # uninstall-autostart
    sub.add_parser("uninstall-autostart", help="Remove Windows autostart task")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "run":
        return _cmd_run(args)
    elif args.command == "profile":
        return _cmd_profile(args)
    elif args.command == "blit-screen":
        return _cmd_blit_screen(args)
    elif args.command == "blit-key":
        return _cmd_blit_key(args)
    elif args.command == "validate":
        return _cmd_validate(args)
    elif args.command == "status":
        return _cmd_status(args)
    elif args.command == "brightness":
        return _cmd_brightness(args)
    elif args.command == "install-autostart":
        return _cmd_install_autostart()
    elif args.command == "uninstall-autostart":
        return _cmd_uninstall_autostart()
    else:
        parser.print_help()
        return 1


def _cmd_run(args) -> int:
    from .daemon import run_daemon
    run_daemon(
        profiles_path=args.profiles,
        interface=args.interface,
        web=not args.no_web,
    )
    return 0


def _cmd_profile(args) -> int:
    try:
        data = profiles_mod.load_profiles(args.profiles)
        profiles_mod.set_active_profile(data, args.name)
        profiles_mod.save_profiles(args.profiles, data)
        print(f"Active profile set to: {args.name}")
        return 0
    except profiles_mod.ProfileError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _wait_for_device(daemon) -> bool:
    """Poll until the link reaches READY/INITIALIZING, then mark it READY.

    A fresh connect parks the link in INITIALIZING (nothing calls mark_ready
    outside the daemon loop), so we must accept that state too.
    """
    import time
    from .usb_link import READY, INITIALIZING
    for _ in range(10):
        state = daemon.link.poll()
        if state in (READY, INITIALIZING):
            break
        time.sleep(0.5)
    if daemon.link.state not in (READY, INITIALIZING):
        return False
    daemon.link.mark_ready()
    return True


def _cmd_blit_screen(args) -> int:
    from .daemon import Daemon
    if not os.path.isfile(args.image):
        print(f"Error: image not found: {args.image}", file=sys.stderr)
        return 1
    daemon = Daemon(
        args.profiles,
        interface=args.interface,
        web=False,
    )
    if not _wait_for_device(daemon):
        print("Error: device not ready", file=sys.stderr)
        return 1
    try:
        daemon.blit_screen(args.image)
    except ConnectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        daemon.link.disconnect()
    return 0


def _cmd_blit_key(args) -> int:
    from .daemon import Daemon
    from .protocol import KEY_COUNT
    if not (0 <= args.key < KEY_COUNT):
        print(f"Error: key must be 0-{KEY_COUNT - 1}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.image):
        print(f"Error: image not found: {args.image}", file=sys.stderr)
        return 1
    daemon = Daemon(
        args.profiles,
        interface=args.interface,
        web=False,
    )
    if not _wait_for_device(daemon):
        print("Error: device not ready", file=sys.stderr)
        return 1
    try:
        daemon.blit_key(args.key, args.image)
    except ConnectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        daemon.link.disconnect()
    return 0


def _cmd_validate(args) -> int:
    try:
        profiles_mod.load_profiles(args.profiles)
        print(f"OK: {args.profiles} is valid.")
        return 0
    except profiles_mod.ProfileError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1


def _cmd_status(args) -> int:
    try:
        data = profiles_mod.load_profiles(args.profiles)
        status = {
            "active_profile": data.get("active_profile"),
            "profiles": list(data.get("profiles", {}).keys()),
            "settings": data.get("settings", {}),
        }
        print(json.dumps(status, indent=2))
        return 0
    except profiles_mod.ProfileError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_brightness(args) -> int:
    if not 0 <= args.percent <= 100:
        print("Error: brightness must be 0-100", file=sys.stderr)
        return 2
    from .brightness import BrightnessController, BrightnessError
    try:
        controller = BrightnessController()
        if args.target == "keys":
            controller.set_key_lcd_brightness(args.percent)
            setting = "brightness"
        else:
            controller.set_keyboard_brightness(args.percent)
            setting = "keyboard_brightness"
        data = profiles_mod.load_profiles(args.profiles)
        data.setdefault("settings", {})[setting] = args.percent
        profiles_mod.save_profiles(args.profiles, data)
        print(f"{args.target} brightness set to {args.percent}%")
        return 0
    except (BrightnessError, profiles_mod.ProfileError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_install_autostart() -> int:
    if os.name != "nt":
        print("Autostart is Windows-only.", file=sys.stderr)
        return 1
    try:
        import subprocess
        import sys as _sys

        exe = _sys.executable
        base = str(BASE_DIR)
        # Task Scheduler runs with cwd=System32, and `cli.py` can't be run as a
        # bare script (its relative imports need the package).  So cd into the
        # project dir and launch via `-m app.cli`.
        run_cmd = f'cmd /c "pushd "{base}" && "{exe}" -m app.cli run"'
        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", "SwitchbladeReborn",
                "/TR", run_cmd,
                "/SC", "ONLOGON",
                "/RL", "LIMITED",
                "/F",
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print("Autostart task installed.")
            print(f"  Command: {run_cmd}")
            return 0
        else:
            print(f"Failed: {result.stderr}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_uninstall_autostart() -> int:
    if os.name != "nt":
        print("Autostart is Windows-only.", file=sys.stderr)
        return 1
    try:
        import subprocess
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", "SwitchbladeReborn", "/F"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print("Autostart task removed.")
            return 0
        else:
            print(f"Failed: {result.stderr}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
