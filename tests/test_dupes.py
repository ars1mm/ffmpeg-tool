"""Tests for hash-based duplicate detection."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from video_converter import dupes


class DuplicateDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dupes_test_"))
        self.addCleanup(lambda: self._rmtree(self.tmp))

    @staticmethod
    def _rmtree(root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass

    def _write(self, rel: str, data: bytes) -> Path:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_finds_identical_files_across_folders(self) -> None:
        data = b"same-content-bytes" * 1024
        self._write("a/one.mp4", data)
        self._write("b/two.mp4", data)
        self._write("c/unique.mp4", b"different" * 1024)

        groups = dupes.find_duplicates(dupes.iter_videos(self.tmp))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].files), 2)
        self.assertIn("one.mp4", groups[0].files[0].name)

    def test_single_files_excluded(self) -> None:
        self._write("only.mp4", b"unique" * 10)
        self.assertEqual(dupes.find_duplicates(dupes.iter_videos(self.tmp)), [])

    def test_same_size_different_content_not_grouped(self) -> None:
        block = b"x" * 4096
        self._write("p.mp4", block)
        self._write("q.mp4", b"y" * 4096)
        self.assertEqual(dupes.find_duplicates(dupes.iter_videos(self.tmp)), [])

    def test_non_video_files_ignored(self) -> None:
        block = b"same" * 100
        self._write("a/two.mp4", block)
        self._write("b/two.mkv", block)
        self._write("c/two.exe", block)
        self._write("d/two.png", block)
        groups = dupes.find_duplicates(dupes.iter_videos(self.tmp))
        files = {p.suffix for g in groups for p in g.files}
        self.assertEqual(files, {".mp4", ".mkv"})

    def test_stop_event_aborts(self) -> None:
        self._write("a/a1.mp4", b"z" * 5000)
        self._write("b/b1.mp4", b"z" * 5000)
        calls = {"n": 0}

        def stop() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        with self.assertRaises(InterruptedError):
            dupes.find_duplicates(dupes.iter_videos(self.tmp),
                                  should_stop=stop)

    def test_progress_reports_candidates(self) -> None:
        block = b"c" * 3000
        self._write("a/x.mp4", block)
        self._write("b/y.mp4", block)
        self._write("z.mp4", b"unique")
        seen: list[int] = []

        def progress(done: int, _total: int, _path: str) -> None:
            seen.append(done)

        dupes.find_duplicates(dupes.iter_videos(self.tmp), progress=progress)
        self.assertEqual(seen[-1], 2)

    def test_groups_not_in_nested_library(self) -> None:
        block = b"nested" * 512
        self._write("top/a.mp4", block)
        self._write("top/sub/a2.mp4", block)
        self._write("top/deep/deeper/a3.mp4", block)
        groups = dupes.find_duplicates(dupes.iter_videos(self.tmp))
        self.assertEqual(len(groups[0].files), 3)


if __name__ == "__main__":
    unittest.main()