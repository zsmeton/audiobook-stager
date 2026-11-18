from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.library_cache import (
    get_inode_index_copy,
    get_library_indexes,
    invalidate_library_cache,
)


class LibraryCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        invalidate_library_cache()

    def tearDown(self) -> None:
        invalidate_library_cache()

    def _make_library(self, root: Path, *, author: str = "Author", title: str = "Title") -> Path:
        target = root / author / title
        target.mkdir(parents=True)
        (target / "book.mp3").write_bytes(b"x" * 100)
        return root

    def test_cache_hit_returns_same_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library_root = self._make_library(Path(tmp) / "lib")
            lib1, inode1 = get_library_indexes(library_root)
            lib2, inode2 = get_library_indexes(library_root)
            self.assertIs(lib1, lib2)
            self.assertIs(inode1, inode2)

    def test_invalidation_rebuilds_after_library_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "lib"
            self._make_library(library_root)

            lib1, _ = get_library_indexes(library_root)
            first_keys = set(lib1.keys())

            extra = library_root / "Other" / "Book"
            extra.mkdir(parents=True)
            (extra / "other.mp3").write_bytes(b"y" * 50)

            lib_stale, _ = get_library_indexes(library_root)
            self.assertIs(lib_stale, lib1)
            self.assertEqual(set(lib_stale.keys()), first_keys)

            invalidate_library_cache(library_root)
            lib_fresh, _ = get_library_indexes(library_root)
            self.assertIsNot(lib_fresh, lib1)
            self.assertIn("Other/Book", lib_fresh)

    def test_inode_copy_isolated_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library_root = self._make_library(Path(tmp) / "lib")
            _, cached_inode = get_library_indexes(library_root)
            copy = get_inode_index_copy(library_root)
            copy[99999] = ["fake/path.mp3"]
            self.assertNotIn(99999, cached_inode)


if __name__ == "__main__":
    unittest.main()
