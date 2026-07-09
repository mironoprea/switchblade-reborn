"""Windows Razer SwitchBlade SDK display backend.

The installed Razer SDK DLL is 32-bit.  Most modern Python installs are
64-bit, so this module talks to the DLL through a tiny persistent x86 .NET
bridge process instead of loading it with ``ctypes``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from . import protocol


DEFAULT_SDK_DIR = Path(r"C:\ProgramData\Razer\SwitchBlade\SDK")
DEFAULT_CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / (
    r"Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
BRIDGE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    / "SwitchbladeReborn"
    / "sdk-bridge"
)


CS_SOURCE = r"""
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

internal static class Program
{
    [StructLayout(LayoutKind.Sequential)]
    private struct NativePoint
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeMessage
    {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public NativePoint pt;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string lpPathName);

    [DllImport("user32.dll")]
    private static extern bool PeekMessage(out NativeMessage lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax, uint wRemoveMsg);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref NativeMessage lpMsg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessage(ref NativeMessage lpMsg);

    [DllImport("RzSwitchbladeSDK2.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int RzSBStart();

    [DllImport("RzSwitchbladeSDK2.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int RzSBStop();

    [DllImport("RzSwitchbladeSDK2.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int RzSBSetImageDynamicKey(int key, int keyState, string imagePath);

    [DllImport("RzSwitchbladeSDK2.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int RzSBSetImageTouchpad(string imagePath);

    private static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.WriteLine("ERR usage");
            return 64;
        }

        SetDllDirectory(args[0]);
        int start = RzSBStart();
        Console.WriteLine("READY 0x" + start.ToString("X8"));
        Console.Out.Flush();
        PumpMessages(1000);
        if (start != 0)
        {
            return 2;
        }

        try
        {
            string line;
            while ((line = Console.ReadLine()) != null)
            {
                string[] parts = line.Split(new char[] {'\t'}, 3);
                if (parts.Length == 0) continue;

                if (parts[0] == "ping")
                {
                    Console.WriteLine("OK ping");
                }
                else if (parts[0] == "touch" && parts.Length == 2)
                {
                    int hr = RzSBSetImageTouchpad(parts[1]);
                    Console.WriteLine((hr == 0 ? "OK " : "ERR ") + "touch 0x" + hr.ToString("X8"));
                }
                else if (parts[0] == "key" && parts.Length == 3)
                {
                    int key = Int32.Parse(parts[1]);
                    int up = RzSBSetImageDynamicKey(key, 1, parts[2]);
                    int down = RzSBSetImageDynamicKey(key, 2, parts[2]);
                    int hr = up != 0 ? up : down;
                    Console.WriteLine((hr == 0 ? "OK " : "ERR ") + "key 0x" + up.ToString("X8") + " 0x" + down.ToString("X8"));
                }
                else if (parts[0] == "stop")
                {
                    Console.WriteLine("OK stop");
                    Console.Out.Flush();
                    break;
                }
                else
                {
                    Console.WriteLine("ERR bad-command");
                }
                Console.Out.Flush();
                PumpMessages(20);
            }
        }
        finally
        {
            RzSBStop();
        }

        return 0;
    }

    private static void PumpMessages(int milliseconds)
    {
        Stopwatch sw = Stopwatch.StartNew();
        do
        {
            NativeMessage msg;
            while (PeekMessage(out msg, IntPtr.Zero, 0, 0, 1))
            {
                TranslateMessage(ref msg);
                DispatchMessage(ref msg);
            }
            Thread.Sleep(10);
        }
        while (sw.ElapsedMilliseconds < milliseconds);
    }
}
"""


class SdkBackendError(RuntimeError):
    """Raised when the SDK backend cannot start or send an image."""


@dataclass
class SdkBackendConfig:
    sdk_dir: Path = DEFAULT_SDK_DIR
    bridge_dir: Path = BRIDGE_DIR
    csc: Optional[Path] = None


def is_sdk_available(sdk_dir: Path = DEFAULT_SDK_DIR) -> bool:
    """Return True when the Windows SDK files needed by the bridge exist."""
    return sys.platform == "win32" and (sdk_dir / "RzSwitchbladeSDK2.dll").is_file()


def find_csc(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return explicit
    if DEFAULT_CSC.is_file():
        return DEFAULT_CSC
    found = shutil.which("csc")
    if found:
        return Path(found)
    raise FileNotFoundError("csc.exe not found; install .NET Framework build tools")


def _compile_bridge(config: SdkBackendConfig) -> Path:
    config.bridge_dir.mkdir(parents=True, exist_ok=True)
    source = config.bridge_dir / "SwitchbladeSdkBridge.cs"
    exe = config.bridge_dir / "SwitchbladeSdkBridge.exe"

    if not source.is_file() or source.read_text(encoding="utf-8") != CS_SOURCE:
        source.write_text(CS_SOURCE, encoding="utf-8")
        if exe.exists():
            exe.unlink()

    if not exe.is_file():
        csc = find_csc(config.csc)
        subprocess.run(
            [
                str(csc),
                "/nologo",
                "/target:exe",
                "/platform:x86",
                f"/out:{exe}",
                str(source),
            ],
            check=True,
        )

    return exe


def rgb565_to_image(
    rgb565: bytes,
    width: int,
    height: int,
    *,
    endian: str = "little",
) -> Image.Image:
    """Convert an RGB565 framebuffer back to a PIL RGB image."""
    if len(rgb565) != width * height * 2:
        raise ValueError(
            f"RGB565 buffer must be {width * height * 2} bytes, got {len(rgb565)}"
        )

    import numpy as np

    dtype = np.dtype("<u2") if endian == "little" else np.dtype(">u2")
    values = np.frombuffer(rgb565, dtype=dtype).reshape((height, width))
    r = ((values >> 11) & 0x1F).astype(np.uint8)
    g = ((values >> 5) & 0x3F).astype(np.uint8)
    b = (values & 0x1F).astype(np.uint8)
    arr = np.dstack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    return Image.fromarray(arr, "RGB")


class SdkDisplayBackend:
    """Persistent display backend for Razer's 32-bit SwitchBlade SDK."""

    def __init__(self, config: Optional[SdkBackendConfig] = None) -> None:
        self.config = config or SdkBackendConfig()
        self._process: Optional[subprocess.Popen[str]] = None
        self._image_dir = self.config.bridge_dir / "images"
        self._counter = 0

    @property
    def started(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.started:
            return
        if not is_sdk_available(self.config.sdk_dir):
            raise SdkBackendError(f"Razer SDK not found: {self.config.sdk_dir}")

        exe = _compile_bridge(self.config)
        self._image_dir.mkdir(parents=True, exist_ok=True)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [str(exe), str(self.config.sdk_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        line = self._readline()
        if not line.startswith("READY 0x00000000"):
            self.close()
            raise SdkBackendError(f"SDK bridge failed to start: {line}")

    def close(self) -> None:
        proc = self._process
        self._process = None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.write("stop\n")
                    proc.stdin.flush()
                    self._readline(proc)
            except (BrokenPipeError, OSError, SdkBackendError):
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()

    def blit_screen_rgb565(self, rgb565: bytes) -> None:
        path = self._save_rgb565_png(
            rgb565,
            protocol.SCREEN_WIDTH,
            protocol.SCREEN_HEIGHT,
            "screen",
        )
        self._command(f"touch\t{path}")

    def blit_key_rgb565(self, key_index: int, rgb565: bytes) -> None:
        if not 0 <= key_index < protocol.KEY_COUNT:
            raise ValueError(f"key index must be 0-{protocol.KEY_COUNT - 1}")
        path = self._save_rgb565_png(
            rgb565,
            protocol.KEY_IMAGE_SIZE,
            protocol.KEY_IMAGE_SIZE,
            f"key{key_index}",
        )
        self._command(f"key\t{key_index + 1}\t{path}")

    def blit_screen_image(self, image_path: str) -> None:
        self._command(f"touch\t{Path(image_path).resolve()}")

    def blit_key_image(self, key_index: int, image_path: str) -> None:
        if not 0 <= key_index < protocol.KEY_COUNT:
            raise ValueError(f"key index must be 0-{protocol.KEY_COUNT - 1}")
        self._command(f"key\t{key_index + 1}\t{Path(image_path).resolve()}")

    def _save_rgb565_png(self, rgb565: bytes, width: int, height: int, stem: str) -> Path:
        self._counter += 1
        path = self._image_dir / f"{stem}-{self._counter:06d}.png"
        rgb565_to_image(rgb565, width, height).save(path)
        return path

    def _command(self, line: str) -> str:
        self.start()
        proc = self._require_process()
        if proc.stdin is None:
            raise SdkBackendError("SDK bridge stdin is closed")
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
        response = self._readline(proc)
        if not response.startswith("OK "):
            raise SdkBackendError(response)
        return response

    def _require_process(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            raise SdkBackendError("SDK bridge is not running")
        return self._process

    def _readline(self, proc: Optional[subprocess.Popen[str]] = None) -> str:
        proc = proc or self._require_process()
        if proc.stdout is None:
            raise SdkBackendError("SDK bridge stdout is closed")
        line = proc.stdout.readline()
        if line == "":
            raise SdkBackendError("SDK bridge exited without a response")
        return line.strip()
