from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.conflicts import build_library_index
from stager_core.staging import build_inode_index
from stager_core.target_index import build_target_indexes


class TargetIndexParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = self.root / "lib"
        self.library.mkdir()
        paths = [
            self.library / "Author" / "Book One" / "part1.m4b",
            self.library / "Author" / "Book One" / "part2.m4b",
            self.library / "Series" / "Vol 1" / "Title" / "book.m4b",
        ]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 64)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_target_indexes_matches_legacy_helpers(self) -> None:
        merged_lib, merged_inode = build_target_indexes(self.library)
        legacy_lib = build_library_index(self.library)
        legacy_inode = build_inode_index(self.library)

        self.assertEqual(set(merged_lib.keys()), set(legacy_lib.keys()))
        for key in merged_lib:
            merged_files = sorted(f["relative_path"] for f in merged_lib[key].files)
            legacy_files = sorted(f["relative_path"] for f in legacy_lib[key].files)
            self.assertEqual(merged_files, legacy_files)

        self.assertEqual(merged_inode, legacy_inode)
