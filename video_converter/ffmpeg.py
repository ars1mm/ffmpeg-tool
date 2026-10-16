"""FFmpeg / ffprobe discovery and media probing helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe cannot be located."""


def _candidate_names(tool: str) -> list[str]:
    names = [tool]
    if os.name == "nt":
        names.append(f"{tool}.exe")
    return names


def _search_local_dirs(tool: str) -> str | None:
    """Look for a bundled binary next to the app or in a ./bin folder."""
    here = Path(__file__).resolve().parent
    roots = [here, here.parent, here.parent / "bin", Path.cwd(), Path.cwd() / "bin"]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.extend([exe_dir, exe_dir / "bin"])
    for root in roots:
        for name in _candidate_names(tool):
            candidate = root / name
            if candidate.is_file():
                return str(candidate)
    return None


@lru_cache(maxsize=None)
def find_tool(tool: str) -> str:
    """Return an absolute path to `tool`, searching PATH and local bins."""
    local = _search_local_dirs(tool)
    if local:
        return local

    found = shutil.which(tool)
    if found:
        return found

    for name in _candidate_names(tool):
        found = shutil.which(name)
        if found:
            return found

    raise FFmpegNotFoundError(
        f"Could not find '{tool}'. Install FFmpeg and add it to PATH, "
        f"or place the binary in a './bin' folder next to the app."
    )


def ffmpeg_path() -> str:
    return find_tool("ffmpeg")


def ffprobe_path() -> str:
    return find_tool("ffprobe")


def _run_no_window(args: list[str]) -> subprocess.CompletedProcess:
    """Run a subprocess without flashing a console window on Windows."""
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        check=False,
    )


@dataclass
class MediaInfo:
    path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    has_video: bool = False
    has_audio: bool = False

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "audio only"


def probe(path: str) -> MediaInfo:
    """Return basic stream info for `path` using ffprobe."""
    info = MediaInfo(path=path)
    args = [
        ffprobe_path(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = _run_no_window(args)
    if result.returncode != 0:
        return info

    try:
        payload = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return info

    fmt = payload.get("format", {})
    try:
        info.duration = float(fmt.get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        info.duration = 0.0

    for stream in payload.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = stream.get("codec_name", "")
            info.width = int(stream.get("width", 0) or 0)
            info.height = int(stream.get("height", 0) or 0)
        elif kind == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = stream.get("codec_name", "")

    return info


@lru_cache(maxsize=None)
def list_encoders() -> list[str]:
    """Return the names of all encoders this ffmpeg build knows."""
    try:
        result = _run_no_window([ffmpeg_path(), "-hide_banner", "-encoders"])
    except FFmpegNotFoundError:
        return []
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    names: list[str] = []
    for line in lines:
        match = re.match(r"^\s*[A-Z]\.{4}\S?\s+(\S+)", line)
        if match:
            names.append(match.group(1))
    return names


def available_hardware_encoders(known: list[str]) -> list[str]:
    """Return encoder names that both exist in this build and are in `known`."""
    present = set(list_encoders())
    return [name for name in known if name in present]


# Pixel formats required by each encoder family (must match GPU_ENCODERS in presets.py)
_ENCODER_PIX_FMT: dict[str, str] = {
    "h264_nvenc":  "yuv420p",
    "hevc_nvenc":  "yuv420p",
    "av1_nvenc":   "yuv420p",
    "h264_amf":    "yuv420p",
    "hevc_amf":    "yuv420p",
    "h264_qsv":    "nv12",
    "hevc_qsv":    "nv12",
    "vp9_qsv":     "nv12",
    "av1_qsv":     "nv12",
}


def probe_hardware_encoder(encoder_name: str) -> bool:
    """Return True if ffmpeg can actually encode 1 frame with *encoder_name*.

    Uses the built-in ``lavfi`` test source so no real input file is needed.
    The output is discarded via the ``nullsink`` (``-f null -``).
    This catches cases where the encoder exists in the ffmpeg build but the
    matching driver / hardware is absent (common on AMD/Intel machines where
    only NVENC is listed, or vice-versa).
    """
    pix_fmt = _ENCODER_PIX_FMT.get(encoder_name, "yuv420p")
    null_out = "NUL" if os.name == "nt" else "/dev/null"
    args = [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        # 1-frame 64x64 test source — tiny, fast, no disk I/O
        "-f", "lavfi", "-i", "color=black:s=64x64:r=1:d=1",
        "-vframes", "1",
        "-c:v", encoder_name,
        "-pix_fmt", pix_fmt,
        "-f", "null", null_out,
    ]
    try:
        result = _run_no_window(args)
        success = result.returncode == 0
        if not success and result.stderr:
            error_msg = result.stderr.decode("utf-8", errors="replace").strip()
            # Only show meaningful errors (not just warnings)
            if "error" in error_msg.lower() or "failed" in error_msg.lower():
                print(f"[gpu] {encoder_name} test failed: {error_msg[:200]}", flush=True)
        return success
    except FFmpegNotFoundError:
        return False


def verified_hardware_encoders(known: list[str]) -> list[str]:
    """Return hardware encoders from *known* that are present in this ffmpeg
    build **and** pass a quick 1-frame encode test on this machine's hardware.

    Falls back to :func:`available_hardware_encoders` if the ffmpeg binary
    cannot be found.
    """
    candidates = available_hardware_encoders(known)
    if not candidates:
        print("[gpu] No hardware encoders found in FFmpeg build", flush=True)
        return []
    
    print(f"[gpu] Found {len(candidates)} encoder(s) in FFmpeg build: {', '.join(candidates)}", flush=True)
    print("[gpu] Testing hardware availability...", flush=True)
    
    verified: list[str] = []
    for name in candidates:
        ok = probe_hardware_encoder(name)
        status = "✓ AVAILABLE" if ok else "✗ not available"
        print(f"[gpu]   {name}: {status}", flush=True)
        if ok:
            verified.append(name)
    
    if verified:
        print(f"[gpu] Successfully verified {len(verified)} hardware encoder(s)", flush=True)
    else:
        print("[gpu] No working hardware encoders found - will use CPU encoding", flush=True)
    
    return verified


def verify_ffmpeg() -> tuple[str, str]:
    """Confirm both binaries respond; return (ffmpeg, ffprobe) versions."""
    ffmpeg = ffmpeg_path()
    ffprobe = ffprobe_path()

    def _version(binary: str) -> str:
        out = _run_no_window([binary, "-version"]).stdout.decode(
            "utf-8", errors="replace"
        )
        return out.splitlines()[0] if out else "unknown"

    _version(ffmpeg)
    _version(ffprobe)
    return _version(ffmpeg), _version(ffprobe)
