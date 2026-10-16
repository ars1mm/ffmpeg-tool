"""Conversion engine: runs FFmpeg and reports progress."""

from __future__ import annotations

import os
import random
import re
import subprocess
import threading
import unicodedata
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .presets import Crop, Preset

ProgressCallback = Callable[[float, str], None]

DEFAULT_TEMPLATE = "{slug}-{hex5}-{uuid}-{time}.{format}"
_INVALID_NAME_CHARS = set('<>:"/\\|?*')


@dataclass
class ConversionResult:
    source: str
    destination: str | None
    success: bool
    cancelled: bool
    message: str
    log: str


def sanitize_component(value: str) -> str:
    """Make a single path component safe for Windows."""
    cleaned = "".join(
        ch for ch in value if ch not in _INVALID_NAME_CHARS and ord(ch) >= 32
    )
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "_"


def slugify(value: str) -> str:
    """Lowercase, ASCII, hyphen-separated slug (e.g. 'Dua Lipa' -> 'dua-lipa')."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "clip"


def generate_tokens() -> dict[str, str]:
    """Fresh uniqueness tokens for one output name."""
    return {
        "hex5": f"{random.getrandbits(20):05X}",
        "uuid": str(uuid_module.uuid4()),
        "time": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
    }


def build_output_path(
    source: str,
    preset: Preset,
    out_dir: str | None,
    template: str = DEFAULT_TEMPLATE,
    artist: str = "",
) -> str:
    """Compute a destination path from a name template.

    Placeholders:
      {format}  output container (mp4, webm, ...)
      {name}    source filename stem
      {artist}  raw artist tag
      {slug}    slugified artist (or source name)
      {hex5}    5 uppercase hex characters
      {uuid}    random UUIDv4
      {time}    current UTC time (YYYYMMDD-HHMMSS)
    Template separators create sub-folders.
    """
    src = Path(source)
    slug_source = artist or src.stem
    values = {
        "format": preset.container,
        "name": sanitize_component(src.stem),
        "artist": sanitize_component(artist) if artist else "",
        "slug": slugify(slug_source),
        **generate_tokens(),
    }

    template = template.strip() or DEFAULT_TEMPLATE
    try:
        rendered = template.format(**values)
    except (KeyError, IndexError, ValueError):
        rendered = DEFAULT_TEMPLATE.format(**values)

    parts = [
        sanitize_component(part)
        for part in re.split(r"[\\/]+", rendered)
        if part not in {"", ".", ".."}
    ]
    if not parts:
        parts = [sanitize_component(src.stem)]

    filename = parts[-1]
    extension = f".{preset.container}"
    if not filename.lower().endswith(extension):
        filename += extension
    parts[-1] = filename

    base = Path(out_dir) if out_dir else src.parent
    if len(parts) > 1:
        target_dir = base.joinpath(*parts[:-1])
    else:
        target_dir = base

    candidate = target_dir / filename
    if candidate.resolve() == src.resolve():
        candidate = target_dir / f"{filename[:-len(extension)]}_converted{extension}"

    counter = 1
    stem = candidate.stem
    while candidate.exists():
        candidate = target_dir / f"{stem}_converted{counter}{extension}"
        counter += 1
    return str(candidate)


def output_path_for(source: str, preset: Preset, out_dir: str | None) -> str:
    """Backwards-compatible simple destination (no template)."""
    return build_output_path(source, preset, out_dir)



def _parse_progress_line(line: str, duration: float) -> float | None:
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if key in {"out_time_ms", "out_time_us"} and value.isdigit() and duration > 0:
        seconds = int(value) / 1_000_000
        return max(0.0, min(1.0, seconds / duration))
    if key == "out_time" and duration > 0:
        try:
            hh, mm, ss = value.split(":")
            seconds = int(hh) * 3600 + int(mm) * 60 + float(ss)
            return max(0.0, min(1.0, seconds / duration))
        except ValueError:
            return None
    return None


def convert(
    source: str,
    destination: str,
    preset: Preset,
    crop: Crop | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    threads: int | None = None,
    gpu_encoder: str | None = None,
) -> ConversionResult:
    """Transcode a single file. Blocking; run from a worker thread.

    When `threads` is set, the encoder and filters are pinned to that many
    CPU threads so a caller can bound total CPU usage across a pool.
    When `gpu_encoder` is set, compatible presets use that hardware encoder.
    """
    cancel_event = cancel_event or threading.Event()
    on_progress = on_progress or (lambda _frac, _msg: None)

    try:
        info = ffmpeg.probe(source)
    except ffmpeg.FFmpegNotFoundError as exc:
        return ConversionResult(source, None, False, False, str(exc), "")

    duration = info.duration

    try:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ConversionResult(
            source, None, False, False, f"Cannot create output folder: {exc}", ""
        )

    args = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
    ]
    if threads:
        args += [
            "-filter_threads",
            str(threads),
            "-filter_complex_threads",
            str(threads),
        ]
    args += [
        "-progress",
        "pipe:1",
        *preset.ffmpeg_args(source, destination, crop, threads, gpu_encoder),
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    log_lines: list[str] = []
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except OSError as exc:
        return ConversionResult(source, None, False, False, str(exc), "")

    assert process.stdout is not None
    try:
        for line in process.stdout:
            if cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                _cleanup(destination)
                return ConversionResult(
                    source, None, False, True, "Cancelled", "".join(log_lines)
                )

            line = line.strip()
            if not line:
                continue
            frac = _parse_progress_line(line, duration)
            if frac is not None:
                on_progress(frac, f"{int(frac * 100)}%")
            elif "frame=" in line or "error" in line.lower():
                log_lines.append(line)
    finally:
        process.stdout.close()

    returncode = process.wait()
    log = "\n".join(log_lines)

    if cancel_event.is_set():
        _cleanup(destination)
        return ConversionResult(source, None, False, True, "Cancelled", log)

    if returncode == 0:
        on_progress(1.0, "100%")
        return ConversionResult(source, destination, True, False, "Done", log)

    _cleanup(destination)
    return ConversionResult(
        source, None, False, False, f"FFmpeg exited with code {returncode}", log
    )


def _cleanup(destination: str) -> None:
    try:
        if os.path.exists(destination):
            os.remove(destination)
    except OSError:
        pass
