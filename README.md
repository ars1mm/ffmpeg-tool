# FFmpeg Video Converter

A small **local** desktop app (Python + Tkinter) that batch-transcodes videos
between common formats and codecs using FFmpeg. Useful for making a library
playable across devices, meeting size/quality limits, or standardizing output.

Everything runs on your machine. No uploads, no accounts, no network access.

## Features

- **Source library**: point at a root folder (e.g., `C:\Videos` or 
  `D:\MyVideos`) and it lists every sub-folder with a video count. 
  Double-click or select folders to queue their videos; the folder name is 
  used as the `{artist}` tag.
- Batch queue: add individual files or a whole folder
- Format presets (container / codec / resolution / quality)
- Flexible output layout via a name template with placeholders
- Optional visible crop / reframe (aspect presets or custom WxH+X+Y)
- UAC "Restart as administrator" for protected output folders
- Parallel conversion pool: half the logical CPUs, one thread per job, so the
  app stays under ~50% CPU. Each finished path is printed to the terminal.
- Per-file progress plus an overall progress bar
- Choose an output folder, or write results next to the source
- Cancel a running batch
- Bundled-binary lookup: drop `ffmpeg.exe`/`ffprobe.exe` in `./bin` if they
  are not on `PATH`

## Threading / CPU use

Conversions are managed as a proper job queue: the configured number of worker
threads each pull one job at a time from a `queue.Queue`. The **Workers**
field (1 to your logical CPU count, default `cpu_count // 2`) sets the pool
size, and every job is pinned with `-threads 1` (plus `-filter_threads 1`), so
total encode CPU stays near `workers / cpu_count`. The queue is locked while a
run is active (add/remove/clear are disabled); the terminal prints
`[pool]`, `[save]`, `[done]` / `[failed]` / `[cancel]` lines as work proceeds.

## Presets

| Preset | Output |
| --- | --- |
| MP4 / H.264 / 1080p, 720p, 480p | Universal playback, three sizes |
| MP4 / H.265 (HEVC) / 1080p, 720p | Higher compression |
| MP4 / AV1 / 1080p | Best modern compression |
| MP4 / VP9 / 1080p | Open codec in MP4 |
| MKV / H.264, MKV / H.265 | Local playback / archival |
| MKV / VP9, MKV / AV1 | Open codecs in MKV |
| WebM / VP9 / 1080p | Open browser format |
| WebM / AV1 / 1080p | Modern browser format |
| MOV / H.264, MOV / H.265 | QuickTime |
| M4V / H.264 | iPod / Apple TV |
| AVI / H.264 | Classic AVI container |
| MPEG-TS / H.264 | Streaming transport stream |
| FLV / H.264 | Legacy Flash |
| Audio only / MP3 | Extract audio |
| Audio only / AAC | Extract audio (m4a) |
| GIF | Short silent clips |

## Duplicate detection

The **Tools → Find duplicate videos** menu (or the **Duplicates** toolbar
button) opens a scan panel. It hashes the library to find byte-identical
copies:

1. Set the root folder (defaults to the source library) and press **Scan**.
   Files are pre-filtered by size, then identical-size candidates are compared
   with streaming SHA-256 hashes.
2. Results are shown grouped; the first file in each group is tagged as the
   keeper, the rest as duplicates.
3. **Select all but first in each group** marks candidates, and **Delete
   selected** moves them to the Windows **Recycle Bin** (undo-capable) so
   nothing is lost permanently.

This compares exact content - it does not detect different encodes of the
same video (e.g. two resolutions of the same clip).

## Source library

The left panel lists the sub-folders of the **Source library** root (e.g.,
`C:\Videos` or your chosen folder), each with the number of video files
it contains (searched recursively). Select one or more folders and click
**Add selected folders to queue** (or double-click). Each video becomes a job,
and the containing folder name is used as that job's `{artist}` value.

The default output folder is the parent of the source root (e.g., if your
source is `C:\Videos\MyCollection`, the output defaults to `C:\Videos`), so 
with the default template the result is organized by format and artist:
`Videos\<format>\<artist>\<slug>-<hex5>-<uuid>-<time>.<format>`.

## Output folder

When you click **Start**, the app will prompt you to select an output folder if one isn't already set. You can:
- Click **Yes** to choose a specific output folder
- Click **No** to save converted files next to the original files

Once set, the output folder is saved and remembered for future sessions. You can change it at any time using the **Choose output** button.

If the output folder doesn't exist, it will be created automatically.

## Output layout

Results are named from a template. Placeholders:

| Placeholder | Meaning | Example |
| --- | --- | --- |
| `{format}` | output container | `mp4` |
| `{name}` | source filename stem | `clip001` |
| `{artist}` | raw artist tag | `music artist` |
| `{slug}` | slugified artist (or source name) | `music-artist` |
| `{hex5}` | 5 uppercase hex chars | `D827B` |
| `{uuid}` | random UUIDv4 | `7c8f99ed-e491-...` |
| `{time}` | current UTC time | `20261012-124030` |

Path separators in the template create sub-folders. Default template:

```
{format}/{artist}/{slug}-{hex5}-{uuid}-{time}.{format}
```

which yields, for example:

```
Videos\mp4\music artist\music-artist-D827B-7c8f99ed-e491-4844-be40-57a1a0b561a0-20261012-124030.mp4
```

Names are sanitized for Windows and never overwritten (a `_converted` suffix
is added on collision).

## Crop / reframe

The **Crop** control reframes the picture before scaling. Options are centred
aspect ratios (16:9, 9:16, 1:1, 4:3, 4:5) or a custom `WxH+X+Y` box. Use
**None** to leave the frame untouched.

## Administrator / protected folders

If the output folder is not writable, the app offers to relaunch elevated via
a UAC prompt. You can also trigger this from **Tools -> Restart as
administrator**. The title bar shows *(Administrator)* when elevated.

## GPU encoding (Hardware Acceleration)

The app **automatically detects** GPU encoders on startup and tests them to ensure they work with your hardware. When hardware is detected:

- **`GPU (auto: best available)`** (the default) automatically picks the best encoder per
  job - e.g. `h264_nvenc` for H.264 presets, `hevc_nvenc` for H.265 presets
  (priority: NVENC > AMF > QSV).
- Individual encoders can also be chosen explicitly from the dropdown.

### Supported hardware encoders

| FFmpeg encoder | Hardware | Example GPUs | Used for |
| --- | --- | --- | --- |
| `h264_amf` / `hevc_amf` | AMD AMF | RX 580, RX 6800, RX 7900 | H.264 / H.265 presets |
| `h264_nvenc` / `hevc_nvenc` / `av1_nvenc` | NVIDIA NVENC | GTX 1060, RTX 3080, RTX 5060 Ti | H.264 / H.265 / AV1 presets |
| `h264_qsv` / `hevc_qsv` / `vp9_qsv` / `av1_qsv` | Intel Quick Sync | Intel UHD 770, Arc A770 | H.264 / H.265 / VP9 / AV1 presets |

### Automatic setup

The app automatically:
1. **Checks your FFmpeg build** for available hardware encoders
2. **Tests each encoder** with a quick 1-frame encode to verify your hardware supports it
3. **Selects the best available** encoder based on your GPU (AMD, NVIDIA, or Intel)
4. Shows a status message like: **"✓ Hardware acceleration ready: AMD AMF"**

### Requirements for GPU encoding

- **FFmpeg with hardware encoder support**: Download a full FFmpeg build from:
  - [Official FFmpeg builds](https://ffmpeg.org/download.html#build-windows)
  - [gyan.dev FFmpeg builds](https://www.gyan.dev/ffmpeg/builds/) (recommended for Windows)
- **Updated GPU drivers**: Ensure your AMD/NVIDIA/Intel drivers are up to date
- For **AMD GPUs** (like RX 580): AMF support is built into recent AMD drivers
- For **NVIDIA GPUs**: NVENC is available on most GTX 10-series and newer
- For **Intel GPUs**: Quick Sync is available on most Intel CPUs with integrated graphics

### Notes

- Only **H.264 / H.265 / VP9 / AV1 presets** can use GPU encoding
- GIF and audio-only presets automatically use CPU
- **Workers with GPU**: Hardware encoding is capped at 2 concurrent jobs to avoid overwhelming the GPU encoder
- If no GPU encoder is detected, the app falls back to CPU encoding (x264/x265)

### Troubleshooting GPU detection

If your GPU isn't detected:

1. **Check FFmpeg build**: Run `ffmpeg -encoders | findstr amf` (AMD), `ffmpeg -encoders | findstr nvenc` (NVIDIA), or `ffmpeg -encoders | findstr qsv` (Intel) to see if hardware encoders are compiled in
2. **Update GPU drivers**: 
   - AMD: Download from [AMD.com](https://www.amd.com/en/support)
   - NVIDIA: Use GeForce Experience or download from [NVIDIA.com](https://www.nvidia.com/Download/index.aspx)
   - Intel: Download from [Intel.com](https://www.intel.com/content/www/us/en/download-center/home.html)
3. **Get a full FFmpeg build**: Some FFmpeg builds don't include hardware encoder support. Download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (Windows)
4. **Check the console output**: The app prints detailed GPU detection results like:
   ```
   [gpu] Found 2 encoder(s) in FFmpeg build: h264_amf, hevc_amf
   [gpu] Testing hardware availability...
   [gpu]   h264_amf: ✓ AVAILABLE
   [gpu]   hevc_amf: ✓ AVAILABLE
   ```

If you see "✗ not available" for an encoder, it means FFmpeg found it but your hardware/driver doesn't support it.

## Build a standalone app (double-click, no commands)

The app is a plain Python/Tkinter GUI, but it can be packaged into a normal
desktop program with PyInstaller:

```powershell
cd <this folder>
.\build_exe.ps1
```

That produces `dist\FFmpegConverter\FFmpegConverter.exe`. **Double-click that
file** - no console, no Python command needed. `ffmpeg.exe` and `ffprobe.exe`
are copied into `dist\FFmpegConverter\bin` so the app runs anywhere (no PATH
setup). Move the whole `FFmpegConverter` folder wherever you like.

Notes:

- Requires Python 3 (from python.org) - the build script installs PyInstaller
  automatically.
- Windowed mode has no console, so the `[pool]`/`[save]`/`[gpu]` lines are
  written to `run.log` next to the exe instead.
- For one portable single `.exe` (slower startup, no folder), pass `-OneFile`.

## Creating a Release

To create a new release with automatic GitHub Actions build:

1. **Update the version** in `video_converter/version.py`:
   ```python
   __version__ = "1.1.0"
   ```

2. **Update CHANGELOG.md** with the new version and changes

3. **Commit your changes**:
   ```powershell
   git add .
   git commit -m "Release v1.1.0"
   ```

4. **Create and push a version tag**:
   ```powershell
   git tag v1.1.0
   git push origin main --tags
   ```

5. GitHub Actions will automatically:
   - Build the Windows executable
   - Download and bundle FFmpeg
   - Create an installer with Inno Setup
   - Create a GitHub Release
   - Upload the installer and portable version

6. Users will be notified of the update when they launch the app

### Manual Release Build

To build releases manually:

```powershell
# Build the executable
.\build_exe.ps1

# Build the installer (requires Inno Setup installed)
.\build_installer.ps1

# Create portable ZIP
.\create_portable_zip.ps1 -Version "1.0.0"
```

## Requirements

- Python 3.10+ (tested on 3.13) with Tkinter (included in the official
  Windows installer)
- FFmpeg on `PATH`, or binaries in a `./bin` folder

Install FFmpeg on Windows:

```powershell
winget install Gyan.FFmpeg
```

## Run

```powershell
python main.py
```

## Tests

Core (non-GUI) integration tests generate a synthetic clip and convert it:

```powershell
python -m unittest discover -s tests -v
```

## Project layout

```
main.py                     entry point
video_converter/
  app.py                    Tkinter UI
  converter.py              conversion engine + progress parsing
  elevation.py              Windows UAC helpers
  ffmpeg.py                 ffmpeg/ffprobe discovery and probing
  presets.py                format presets + crop helpers
tests/
  test_smoke.py
```

## Scope

This tool changes a video's **encoding/container** for compatibility, plus an
optional, visible reframing crop. Output names come from a template and may
include uniqueness tokens (`{hex5}`, `{uuid}`, `{time}`); filenames are
metadata and do not change the video's content or content hashes. It does not
add, remove, or fake content fingerprints, and it keeps original metadata
intact (`-map_metadata 0`).
