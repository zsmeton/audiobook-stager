from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stager_core.metadata.duration import (
    read_duration_seconds,
    sum_file_durations,
    sum_library_target_durations,
)


class DurationTests(unittest.TestCase):
    def test_sum_file_durations_totals_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [
                {"name": "a.m4b", "source": "book/a.m4b"},
                {"name": "b.m4b", "source": "book/b.m4b"},
            ]

            def fake_read(path: Path) -> float:
                if path.name == "a.m4b":
                    return 3600.0
                if path.name == "b.m4b":
                    return 1800.5
                return 0.0

            with patch(
                "stager_core.metadata.duration.read_duration_seconds",
                side_effect=fake_read,
            ):
                result = sum_file_durations(files, root)

            self.assertEqual(result["total_duration_seconds"], 5400)
            self.assertEqual(len(result["files"]), 2)
            self.assertEqual(result["files"][0]["duration_seconds"], 3600)
            self.assertEqual(result["files"][1]["duration_seconds"], 1800)

    def test_sum_file_durations_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = sum_file_durations([], Path(tmp))
            self.assertEqual(result["total_duration_seconds"], 0)
            self.assertEqual(result["files"], [])

    def test_read_duration_missing_file(self) -> None:
        self.assertEqual(read_duration_seconds(Path("/nonexistent/file.m4b")), 0.0)

    def test_sum_library_target_durations_no_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = sum_library_target_durations(Path(tmp), "Author/Title")
            self.assertEqual(result["total_duration_seconds"], 0)
            self.assertEqual(result["files"], [])

    def test_sum_library_target_durations_sums_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "Author Name" / "Book Title"
            target.mkdir(parents=True)
            (target / "book.m4b").write_bytes(b"x")

            with patch(
                "stager_core.metadata.duration.read_duration_seconds",
                return_value=7200.0,
            ):
                result = sum_library_target_durations(root, "Author Name/Book Title")

            self.assertEqual(result["total_duration_seconds"], 7200)
            self.assertEqual(result["files"][0]["name"], "book.m4b")
