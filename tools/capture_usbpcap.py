#!/usr/bin/env python3
"""Capture USBPcap traffic across root hubs for later analysis.

USBPcapCMD captures one root hub at a time.  This helper starts several capture
processes in parallel so you do not need to know which hub the DeathStalker is
on.  Stop with Ctrl+C after performing the hardware action in Synapse.

Example:

    python tools/capture_usbpcap.py --name 02-set-key-image --seconds 60
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


DEFAULT_USBPCAP = r"C:\Program Files\USBPcap\USBPcapCMD.exe"


def build_command(
    exe: str,
    root_index: int,
    output: Path,
    *,
    snaplen: int,
    all_devices: bool = True,
) -> list[str]:
    cmd = [
        exe,
        "-d",
        rf"\\.\USBPcap{root_index}",
        "-o",
        str(output),
        "-s",
        str(snaplen),
    ]
    if all_devices:
        cmd.append("-A")
    return cmd


def start_captures(
    roots: Iterable[int],
    *,
    exe: str,
    output_dir: Path,
    name: str,
    snaplen: int,
) -> list[tuple[int, Path, subprocess.Popen]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    captures = []
    for root in roots:
        output = output_dir / f"{name}-usbpcap{root}.pcap"
        proc = subprocess.Popen(
            build_command(exe, root, output, snaplen=snaplen),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        captures.append((root, output, proc))
    return captures


def stop_captures(captures: list[tuple[int, Path, subprocess.Popen]]) -> None:
    for _root, _output, proc in captures:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 5.0
    for _root, _output, proc in captures:
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()


def print_results(captures: list[tuple[int, Path, subprocess.Popen]]) -> None:
    for root, output, proc in captures:
        size = output.stat().st_size if output.exists() else 0
        status = "ok" if size else "empty"
        print(f"USBPcap{root}: {status} {size} bytes -> {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="capture", help="output file prefix")
    parser.add_argument("--seconds", type=float, default=0.0, help="capture duration; 0 waits for Ctrl+C")
    parser.add_argument("--roots", default="1-8", help="root range/list, e.g. 1-8 or 1,3,6")
    parser.add_argument("--output-dir", type=Path, default=Path("captures"))
    parser.add_argument("--usbpcap", default=DEFAULT_USBPCAP)
    parser.add_argument("--snaplen", type=int, default=1000000)
    args = parser.parse_args()

    roots = _parse_roots(args.roots)
    captures = start_captures(
        roots,
        exe=args.usbpcap,
        output_dir=args.output_dir,
        name=args.name,
        snaplen=args.snaplen,
    )
    print(f"Capturing on USBPcap roots: {', '.join(map(str, roots))}")
    print("Perform the Synapse/device action now. Press Ctrl+C to stop.")

    try:
        if args.seconds > 0:
            time.sleep(args.seconds)
        else:
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        stop_captures(captures)

    print_results(captures)
    return 0


def _parse_roots(value: str) -> list[int]:
    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(part.strip()) for part in value.split(",") if part.strip()]


if __name__ == "__main__":
    sys.exit(main())
