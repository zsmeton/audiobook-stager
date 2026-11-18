from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.api import bulk_approve, holder
from app.auto import AutoRunManager
from app.db import _utcnow, connect
from app.scan import ScanManager
from app.session import StagingSession


def _insert_pending_book(
    conn,
    book_id: str,
    *,
    source_path: str,
    file_source: str,
    author: str,
    title: str,
) -> None:
    files = [{"name": f"{book_id}.m4b", "source": file_source, "size_bytes": 9}]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0.95, '', '{}', '[]', 'ok', ?)
        """,
        (
            book_id,
            source_path,
            json.dumps(source_path.split("/")),
            "seed",
            "",
            "folder",
            book_id,
            book_id,
            json.dumps(files),
            author,
            title,
            author,
            title,
            _utcnow(),
        ),
    )
    conn.commit()


class BulkApproveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()

        for book_id in ("book1", "book2", "book3"):
            book_dir = self.books / "seed" / book_id
            book_dir.mkdir(parents=True)
            (book_dir / f"{book_id}.m4b").write_bytes(b"audio-data")

        self.conn = connect(self.root / "test.db")
        holder.session = StagingSession(self.books, self.library)
        holder.session.rebuild_target_indexes()
        self.scan_manager = ScanManager(self.conn, self.books, self.library, holder.session)
        self.auto_manager = AutoRunManager(self.conn, self.scan_manager, holder.session)
        holder.conn = self.conn
        holder.manager = self.scan_manager
        holder.auto_manager = self.auto_manager

        _insert_pending_book(
            self.conn,
            "book1",
            source_path="seed/book1",
            file_source="seed/book1/book1.m4b",
            author="Author One",
            title="First Book",
        )
        _insert_pending_book(
            self.conn,
            "book2",
            source_path="seed/book2",
            file_source="seed/book2/book2.m4b",
            author="Author Two",
            title="Second Book",
        )
        _insert_pending_book(
            self.conn,
            "book3",
            source_path="seed/book3",
            file_source="seed/book3/book3.m4b",
            author="Author Three",
            title="Third Book",
        )

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.auto_manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_bulk_approve_stages_multiple_books(self) -> None:
        class BulkApproveBody:
            book_ids = ["book1", "book2", "book3"]

        result = bulk_approve(BulkApproveBody())

        self.assertEqual(len(result["approved"]), 3)
        self.assertEqual(result["errors"], [])
        for book_id in ("book1", "book2", "book3"):
            row = self.conn.execute(
                "SELECT status, staged_path FROM books WHERE id = ?", (book_id,)
            ).fetchone()
            self.assertEqual(row["status"], "staged")
            self.assertTrue(row["staged_path"])
            self.assertTrue(
                (self.library / row["staged_path"].replace("/", "\\")).with_suffix(".m4b").exists()
                or (self.library / row["staged_path"].replace("/", "\\") / f"{book_id}.m4b").exists()
            )


if __name__ == "__main__":
    unittest.main()
