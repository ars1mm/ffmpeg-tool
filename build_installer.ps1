# build_installer.ps1
#
# One command to produce a distributable Windows installer:
#
#   .\build_installer.ps1
#
# What it does:
#   1. Ensures Python is installed (must be on PATH or installed via winget)
#   2. Runs build_exe.ps1 to produce the PyInstaller one-folder bundle
#      with ffmpeg/ffprobe bundled in bin\
#   3. Auto-downloads and installs Inno Setup 6 if not present
#   4. Compiles installer.iss with iscc to produce:
#        installer_output\FFmpegConverter-Setup.exe
#
# Target machines need nothing installed - Python, FFmpeg, and all
# dependencies are embedded in the installer.

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helper: write a coloured status line
# ---------------------------------------------------------------------------
function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host ">>> $msg" -ForegroundColor Cyan
}

# ---------------------------------------------------------------------------
# 1. Verify Python
# ---------------------------------------------------------------------------
Write-Step "Checking Python..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Attempting install via winget..."
    winget install --id Python.Python.3.13 --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Python installation failed. Install manually from https://www.python.org/downloads/ and rerun."
    }
    # Refresh PATH so the new python.exe is visible in this session.
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python still not on PATH after install. Open a new terminal and rerun this script."
    }
}
Write-Host "Python: $((Get-Command python).Source)"

# ---------------------------------------------------------------------------
# 2. Build the PyInstaller bundle
# ---------------------------------------------------------------------------
Write-Step "Building PyInstaller bundle (one-folder)..."
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $ScriptDir "build_exe.ps1")
if ($LASTEXITCODE -ne 0) { throw "build_exe.ps1 failed." }

# Verify the bundle exists before proceeding.
$BundleExe = Join-Path $ScriptDir "dist\FFmpegConverter\FFmpegConverter.exe"
if (-not (Test-Path $BundleExe)) {
    throw "Bundle not found at $BundleExe - check build_exe.ps1 output above."
}
Write-Host "Bundle OK: $BundleExe"

# ---------------------------------------------------------------------------
# 3. Find or install Inno Setup
# ---------------------------------------------------------------------------
Write-Step "Locating Inno Setup compiler (iscc.exe)..."

# Search for iscc.exe: PATH first, then Program Files and user-level installs.
$IsccOnPath = Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
$IsccExe = if ($IsccOnPath -and (Test-Path $IsccOnPath)) {
    $IsccOnPath
} else {
    $searchRoots = @(
        "C:\Program Files",
        "C:\Program Files (x86)",
        "$env:LOCALAPPDATA\Programs"
    ) | Where-Object { Test-Path $_ }
    Get-ChildItem -Path $searchRoots -Filter "ISCC.exe" -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if ($IsccExe) {
    Write-Host "Found Inno Setup: $IsccExe"
} else {
    Write-Host "Inno Setup not found. Installing via winget (JRSoftware.InnoSetup)..."
    # winget returns non-zero for "already installed / no upgrade available" - ignore exit code.
    winget install --id JRSoftware.InnoSetup --source winget --accept-source-agreements --accept-package-agreements
    # (exit code intentionally not checked)

    # Refresh PATH so iscc.exe is visible in this session.
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")

    # Search all installed Inno Setup versions.
    $searchRoots = @(
        "C:\Program Files",
        "C:\Program Files (x86)",
        "$env:LOCALAPPDATA\Programs"
    ) | Where-Object { Test-Path $_ }
    $IsccExe = Get-ChildItem -Path $searchRoots -Filter "ISCC.exe" -Recurse -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending |
               Select-Object -First 1 -ExpandProperty FullName

    if (-not $IsccExe) {
        throw "Inno Setup installed but iscc.exe not found. Open a new terminal and rerun this script."
    }
    Write-Host "Inno Setup found: $IsccExe"
}

# ---------------------------------------------------------------------------
# 4. Compile the installer
# ---------------------------------------------------------------------------
Write-Step "Compiling installer with Inno Setup..."
$IssFile = Join-Path $ScriptDir "installer.iss"
& $IsccExe $IssFile
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
$Output = Join-Path $ScriptDir "installer_output\FFmpegConverter-Setup.exe"
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Installer ready:" -ForegroundColor Green
Write-Host "   $Output" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Share FFmpegConverter-Setup.exe with any Windows 10/11 64-bit user."
Write-Host "No Python, no FFmpeg, no extra steps required on their machine."
Write-Host ""
