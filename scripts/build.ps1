param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SkipTests) {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    python -m app.cli validate
    if ($LASTEXITCODE -ne 0) { throw "Profile validation failed." }
}

foreach ($directory in @("build", "dist", "release")) {
    $target = Join-Path $Root $directory
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

python -m PyInstaller --noconfirm --clean packaging\SwitchbladeReborn.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$Executable = Join-Path $Root "dist\SwitchbladeReborn\SwitchbladeReborn.exe"
& $Executable --smoke-test
if ($LASTEXITCODE -ne 0) { throw "Packaged smoke test failed." }

if (-not $SkipInstaller) {
    $Candidates = @(
        $env:ISCC_PATH,
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if (-not $Candidates) {
        throw "Inno Setup 6 was not found. Set ISCC_PATH or use -SkipInstaller."
    }
    $Iscc = @($Candidates)[0]
    & $Iscc "installer\SwitchbladeReborn.iss"
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
}

Write-Host "Build complete."
