"""Entry point: launch the FFmpeg Video Converter desktop app."""

import os
import sys
from pathlib import Path


def _redirect_streams_to_log() -> None:
    """Windowed mode has no console; keep ffmpeg prints in a log file."""
    if sys.stdout is not None and hasattr(sys.stdout, "write"):
        return
    log_dir = Path(sys.executable).resolve().parent if getattr(
        sys, "frozen", False
    ) else Path.cwd()
    try:
        stream = open(log_dir / "run.log", "a+", buffering=1, encoding="utf-8")
    except OSError:
        log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        try:
            stream = open(log_dir / "FFmpegConverter.log", "a+",
                          buffering=1, encoding="utf-8")
        except OSError:
            return
    sys.stdout = stream
    sys.stderr = stream


if __name__ == "__main__":
    _redirect_streams_to_log()
    from video_converter.app import main

    main()