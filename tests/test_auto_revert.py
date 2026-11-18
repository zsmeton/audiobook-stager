from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from stager_core.discovery import AudioFile, FlatBook
from stager_core.staging import stage_book_author_title, unstage_book


class AutoRevertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "books"
        self.library = self.root / "library"
        self.source.mkdir()
        self.library.mkdir()
        self.book_dir = self.source / "seed" / "book"
        self.book_dir.mkdir(parents=True)
        self.file_path = self.book_dir / "book.m4b"
        self.file_path.write_bytes(b"audio-data")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _flatbook(self) -> FlatBook:
        rel = "seed/book/book.m4b"
        return FlatBook(
            id="book1",
            flatten_name="book",
            source_path="seed/book",
            source_path_parts=["seed", "book"],
            top_level_pack="seed",
            parent_context="",
            grouping="folder",
            files=[AudioFile(name="book.m4b", source=rel, size_bytes=9)],
            flatten_target="book",
        )

    def test_unstage_removes_hardlink(self) -> None:
        book = self._flatbook()
        inode_index: dict[int, list[str]] = {}
        staged = stage_book_author_title(
            self.source,
            self.library,
            book,
            "Test Author",
            "Test Title",
            inode_index,
            dry_run=False,
        )
        self.assertEqual(staged.status, "staged")
        target = self.library / "Test Author" / "Test Title" / "book.m4b"
        self.assertTrue(target.is_file())
        self.assertTrue(os.path.samefile(self.file_path, target))

        result = unstage_book(self.source, self.library, book, staged.target_path)
        self.assertEqual(result.status, "unstaged")
        self.assertFalse(target.exists())
        self.assertTrue(self.file_path.is_file())

    def test_unstage_skips_foreign_inode(self) -> None:
        book = self._flatbook()
        target_dir = self.library / "Other Author" / "Other Title"
        target_dir.mkdir(parents=True)
        foreign = target_dir / "book.m4b"
        foreign.write_bytes(b"other-data")
        result = unstage_book(self.source, self.library, book, "Other Author/Other Title")
        self.assertEqual(result.status, "inode_mismatch")
        self.assertTrue(foreign.is_file())


if __name__ == "__main__":
    unittest.main()
