from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

root = Path(SPECPATH).parent

datas = [
    (str(root / "profiles" / "profiles.json"), "profiles"),
    (str(root / "app" / "webui" / "templates"), "app/webui/templates"),
]
for name in ["bg.png", *[f"key{index}.png" for index in range(10)]]:
    datas.append((str(root / "profiles" / "images" / name), "profiles/images"))
binaries = collect_dynamic_libs("libusb_package")
hiddenimports = ["hid", "pystray._win32", "win32api", "win32con", "win32gui"]

a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SwitchbladeReborn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="SwitchbladeReborn",
)
