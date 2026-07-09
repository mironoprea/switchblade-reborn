param(
    [string]$Name = "sdk-key1-touchpad",
    [int[]]$Roots = @(1, 2, 3, 4, 5, 6, 7, 8),
    [int[]]$Keys = @(1),
    [int]$HoldSeconds = 10,
    [switch]$AllKeys,
    [switch]$NoTouchpad,
    [string]$Python = "python",
    [string]$UsbPcap = "C:\Program Files\USBPcap\USBPcapCMD.exe",
    [string]$OutputDir = "captures",
    [string]$Log = "",
    [string]$ProjectDir = ""
)

$ErrorActionPreference = "Continue"

if (-not $ProjectDir) {
    $ProjectDir = Split-Path -Parent $PSScriptRoot
}
Set-Location -LiteralPath $ProjectDir

if (-not $Log) {
    $Log = Join-Path $OutputDir "$Name.log"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Start-Transcript -Path $Log -Force

try {
    Write-Host "Working directory: $(Get-Location)"
    Write-Host "Starting USBPcap captures for roots: $($Roots -join ', ')"

    $procs = @()
    foreach ($root in $Roots) {
        $out = Join-Path $OutputDir ("{0}-usbpcap{1}.pcap" -f $Name, $root)
        $stdout = Join-Path $OutputDir ("{0}-usbpcap{1}.out" -f $Name, $root)
        $stderr = Join-Path $OutputDir ("{0}-usbpcap{1}.err" -f $Name, $root)
        Remove-Item -LiteralPath $out -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stdout -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderr -ErrorAction SilentlyContinue

        $args = @(
            "-d", ("\\.\USBPcap{0}" -f $root),
            "-o", $out,
            "-s", "1000000",
            "-A",
            "--inject-descriptors"
        )
        Write-Host "USBPcap$root -> $out"
        $procs += Start-Process `
            -FilePath $UsbPcap `
            -ArgumentList $args `
            -PassThru `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr
    }

    Start-Sleep -Seconds 2

    $sdkArgs = @("tools\sdk_exerciser.py", "--hold-seconds", "$HoldSeconds")
    if ($AllKeys) {
        $sdkArgs += "--all-keys"
    } else {
        foreach ($key in $Keys) {
            $sdkArgs += @("--key", "$key")
        }
    }
    if ($NoTouchpad) {
        $sdkArgs += "--no-touchpad"
    }

    Write-Host "Running SDK exerciser: $Python $($sdkArgs -join ' ')"
    & $Python @sdkArgs
    Write-Host "SDK exerciser exit=$LASTEXITCODE"

    Start-Sleep -Seconds 2
}
finally {
    if ($procs) {
        foreach ($proc in $procs) {
            if (-not $proc.HasExited) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 1
    Get-ChildItem -Path $OutputDir -Filter "$Name-usbpcap*.pcap" |
        Select-Object Name, Length |
        Format-Table -AutoSize
    Get-ChildItem -Path $OutputDir -Include "$Name-usbpcap*.out", "$Name-usbpcap*.err" -File |
        Where-Object { $_.Length -gt 0 } |
        ForEach-Object {
            Write-Host "==== $($_.Name) ===="
            Get-Content -LiteralPath $_.FullName
        }
    Stop-Transcript
}
