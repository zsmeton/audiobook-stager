from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.metadata.paths import (
    resolve_library_target_path,
    resolve_seed_source_path,
)


class PathResolutionTests(unittest.TestCase):
    def test_resolve_seed_source_path_joins_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "Some Pack" / "Author - Title"
            book_dir.mkdir(parents=True)
            result = resolve_seed_source_path(root, "Some Pack/Author - Title")
            self.assertEqual(result, str(book_dir.resolve()))

    def test_resolve_seed_source_path_empty_relative_returns_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve_seed_source_path(root, ""), str(root.resolve()))

    def test_resolve_library_target_path_returns_target_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "Author Name" / "Book Title"
            target.mkdir(parents=True)
            result = resolve_library_target_path(root, "Author Name/Book Title")
            self.assertEqual(result, str(target.resolve()))

    def test_resolve_library_target_path_invalid_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_library_target_path(Path(tmp), "no-slash"), "")


if __name__ == "__main__":
    unittest.main()
