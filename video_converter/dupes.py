"""Duplicate detection for the video library.

Files are pre-filtered by size (fast), then identical-size candidates are
compared with SHA-256 streaming hashes. Only byte-for-byte duplicates are
reported - this is a safe library-cleanup tool, not a content fingerprint.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts", ".flv",
    ".mpg", ".mpeg", ".wmv", ".3gp", ".3g2", ".ogv", ".m2ts", ".mts",
}

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class DuplicateGroup:
    """Files that share the exact same content hash."""

    size: int
    sha256: str
    files: tuple[Path, ...] = field(default_factory=tuple)


ProgressCallback = Callable[[int, int, str], None]
StopCallback = Callable[[], bool]


def iter_videos(root: Path) -> Iterator[Path]:
    """Yield every video file below `root`, recursively."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in VIDEO_EXTS:
                yield path


def sha256_file(
    path: Path,
    chunk_size: int = CHUNK_SIZE,
    progress: ProgressCallback | None = None,
    should_stop: StopCallback | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            if should_stop is not None and should_stop():
                raise InterruptedError("stopped")
            block = fh.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def find_duplicates(
    files: Iterable[Path],
    progress: ProgressCallback | None = None,
    should_stop: StopCallback | None = None,
) -> list[DuplicateGroup]:
    """Return groups of byte-identical files.

    Files are bucketed by size first; only size-colliding files are hashed.
    Groups with fewer than two members are dropped.
    """
    by_size: dict[int, list[Path]] = {}
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 0:
            by_size.setdefault(size, []).append(path)

    candidates = [paths for paths in by_size.values() if len(paths) > 1]
    total = sum(len(x) for x in candidates)
    done = 0

    hashed: dict[tuple[int, str], list[Path]] = {}
    for paths in candidates:
        if should_stop is not None and should_stop():
            raise InterruptedError("stopped")
        for path in paths:
            if should_stop is not None and should_stop():
                raise InterruptedError("stopped")
            digest = sha256_file(path, progress=progress, should_stop=should_stop)
            if progress is not None:
                done += 1
                progress(done, total, str(path))
            hashed.setdefault((path.stat().st_size, digest), []).append(path)

    groups = [
        DuplicateGroup(size=size, sha256=digest, files=tuple(paths))
        for (size, digest), paths in hashed.items()
        if len(paths) > 1
    ]
    groups.sort(key=lambda g: g.size, reverse=True)
    return groups