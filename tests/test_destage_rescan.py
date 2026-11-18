from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.db import connect
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.discovery import discover_books
from stager_core.metadata.types import TagInfo
from stager_core.staging import build_inode_index


class DestageRescanTests(unittest.TestCase):
    """A book whose library hardlinks are deleted must return to 'pending'."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()

        # A single-file book in the source ("seeding") tree.
        book_dir = self.books / "seed" / "Great Book"
        book_dir.mkdir(parents=True)
        self.source_file = book_dir / "book.m4b"
        self.source_file.write_bytes(b"audio-bytes")

        self.conn = connect(self.root / "test.db")
        self.session = StagingSession(self.books, self.library)
        self.session.rebuild_target_indexes()
        self.scan_manager = ScanManager(
            self.conn, self.books, self.library, self.session
        )
        # Avoid any network metadata lookups during the test.
        self.scan_manager.lookup.lookup_book = lambda *a, **k: ([], TagInfo())

        books = discover_books(self.books)
        self.assertEqual(len(books), 1)
        self.book = books[0]

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _status(self) -> str:
        row = self.conn.execute(
            "SELECT status FROM books WHERE id = ?", (self.book.id,)
        ).fetchone()
        return row["status"] if row else ""

    def test_deleted_library_copy_returns_to_pending(self) -> None:
        # Stage the book by hardlinking the source into the library.
        target_dir = self.library / "Author" / "Great Book"
        target_dir.mkdir(parents=True)
        link = target_dir / "book.m4b"
        os.link(self.source_file, link)

        inode_index = build_inode_index(self.library)
        self.scan_manager._upsert_book("scan1", self.book, inode_index)
        self.assertEqual(self._status(), "staged")

        # Operator deletes the library copy to re-test the metadata system.
        link.unlink()
        inode_index = build_inode_index(self.library)
        self.assertEqual(inode_index, {})

        self.scan_manager._upsert_book("scan2", self.book, inode_index)
        self.assertEqual(self._status(), "pending")

    def test_still_staged_book_stays_staged(self) -> None:
        target_dir = self.library / "Author" / "Great Book"
        target_dir.mkdir(parents=True)
        os.link(self.source_file, target_dir / "book.m4b")

        inode_index = build_inode_index(self.library)
        self.scan_manager._upsert_book("scan1", self.book, inode_index)
        self.assertEqual(self._status(), "staged")

        # Re-scan with the library copy intact: stays staged.
        inode_index = build_inode_index(self.library)
        self.scan_manager._upsert_book("scan2", self.book, inode_index)
        self.assertEqual(self._status(), "staged")


if __name__ == "__main__":
    unittest.main()
