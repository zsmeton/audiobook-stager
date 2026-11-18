from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stager_core.discovery import AudioFile, FlatBook
from stager_core.staging import BookResult

from app.session import StagingSession


class StagingSessionTests(unittest.TestCase):
    def _make_library(self, root: Path) -> Path:
        target = root / "Author" / "Title"
        target.mkdir(parents=True)
        (target / "book.mp3").write_bytes(b"x" * 100)
        return root

    def test_apply_stage_updates_indexes_without_rglob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library_root = self._make_library(Path(tmp) / "lib")
            books_root = Path(tmp) / "src"
            seed = books_root / "seed" / "book.mp3"
            seed.parent.mkdir(parents=True)
            seed.write_bytes(b"x" * 100)

            session = StagingSession(books_root, library_root)
            session.rebuild_target_indexes("scan1")
            initial_keys = set(session.library_index.keys())

            book = FlatBook(
                id="b1",
                flatten_name="Title",
                source_path="seed",
                source_path_parts=["seed"],
                top_level_pack="seed",
                parent_context="",
                grouping="folder",
                files=[AudioFile(name="book.mp3", source="seed/book.mp3", size_bytes=100)],
            )
            result = BookResult(
                book_id="b1",
                author="Author",
                title="Title",
                source_path="seed",
                target_path="Author/Title",
                status="staged",
                files_linked=1,
            )

            with patch("stager_core.conflicts.build_library_index") as mock_build:
                session.apply_stage(book, result)
                mock_build.assert_not_called()

            self.assertIn("Author/Title", session.library_index)
            self.assertGreater(len(session.inode_index), 0)
            self.assertEqual(initial_keys, {"Author/Title"})

    def test_rebuild_target_indexes_called_once_per_scan_not_per_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library_root = self._make_library(Path(tmp) / "lib")
            session = StagingSession(Path(tmp) / "src", library_root)

            with patch(
                "app.session.build_target_indexes",
                wraps=__import__(
                    "stager_core.target_index",
                    fromlist=["build_target_indexes"],
                ).build_target_indexes,
            ) as mock_index:
                session.rebuild_target_indexes("scan1")
                self.assertEqual(mock_index.call_count, 1)


if __name__ == "__main__":
    unittest.main()
