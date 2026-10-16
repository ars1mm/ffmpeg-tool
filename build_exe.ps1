# Builds the app into a double-clickable Windows desktop app with PyInstaller.
#
#   .\build_exe.ps1            # one-folder bundle  (default)
#   .\build_exe.ps1 -OneFile   # single portable .exe (slower startup)
#
# Produces:
#   dist\FFmpegConverter\FFmpegConverter.exe  (one-folder, default)
#   dist\FFmpegConverter.exe                  (one-file, with -OneFile)
#
# FFmpeg binaries are copied into dist\FFmpegConverter\bin automatically.
# No Python or FFmpeg needed on the target machine.

param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is required to build. Install Python 3 from python.org first."
}

$PythonExe = (Get-Command python).Source
Write-Host "Using Python: $PythonExe"

# Ensure PyInstaller is available.
& $PythonExe -m pip install --disable-pip-version-check --quiet pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed." }

# Locate the linked ffmpeg/ffprobe binaries to bundle beside the app.
$FfmpegExe  = (Get-Command ffmpeg  -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
$FfprobeExe = (Get-Command ffprobe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $FfmpegExe -or -not $FfprobeExe) {
    Write-Warning "ffmpeg/ffprobe not found on PATH - the built app will need them in dist\FFmpegConverter\bin."
}

# Build arguments common to both modes.
$PyiArgs = @(
    "--noconfirm", "--clean", "--windowed",
    "--name", "FFmpegConverter",
    "--distpath", "dist",
    "--workpath", "build"
)

if ($OneFile) {
    Write-Host "Building single-file .exe ..."
    $PyiArgs += "--onefile"
} else {
    Write-Host "Building one-folder bundle ..."
    $PyiArgs += "--onedir"
}

& $PythonExe -m PyInstaller @PyiArgs main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

# Copy ffmpeg + ffprobe into bin\ (one-folder mode only; one-file bundles
# must find ffmpeg on PATH or have the user place it next to the exe).
if (-not $OneFile) {
    $BinDir = Join-Path (Get-Location) "dist\FFmpegConverter\bin"
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    if ($FfmpegExe)  { Copy-Item -Force $FfmpegExe  (Join-Path $BinDir "ffmpeg.exe")  }
    if ($FfprobeExe) { Copy-Item -Force $FfprobeExe (Join-Path $BinDir "ffprobe.exe") }
    Write-Host ""
    Write-Host "Done. Run the app by double-clicking:"
    Write-Host "  $((Get-Location).Path)\dist\FFmpegConverter\FFmpegConverter.exe"
} else {
    Write-Host ""
    Write-Host "Done. Single-file exe:"
    Write-Host "  $((Get-Location).Path)\dist\FFmpegConverter.exe"
    Write-Host "NOTE: ffmpeg/ffprobe must be on PATH or in the same folder as the exe."
}

Write-Host ""
