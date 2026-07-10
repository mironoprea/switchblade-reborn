# Development and release

## Verify

```powershell
python -m pip install -e ".[dev,build]"
python -m pytest -q
python -m app.cli validate
python -m ruff check app tests tools
```

Tests do not require attached hardware. Manual release gates are tracked in
`IMPLEMENTATION_PLAN.md`.

## Build

```powershell
.\scripts\build.ps1
```

The script runs tests, builds a one-folder PyInstaller application, performs a
packaged smoke test, and invokes Inno Setup when `ISCC.exe` is installed. Output
is written to `release/`.

The installer is per-user and does not modify hardware drivers. Executable and
installer signing use `SIGNTOOL_PATH` and `SIGNING_CERT_SHA1` when supplied by
the publisher.

## Versioning

Update `pyproject.toml`, `installer/SwitchbladeReborn.iss`, and `CHANGELOG.md`
together. Tags use `vMAJOR.MINOR.PATCH`.
