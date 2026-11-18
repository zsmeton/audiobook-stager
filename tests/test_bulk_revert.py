from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app.main
from app.api import bulk_approve, bulk_revert, holder
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


class BulkRevertTests(unittest.TestCase):
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

        for book_id, author, title in (
            ("book1", "Author One", "First Book"),
            ("book2", "Author Two", "Second Book"),
            ("book3", "Author Three", "Third Book"),
        ):
            _insert_pending_book(
                self.conn,
                book_id,
                source_path=f"seed/{book_id}",
                file_source=f"seed/{book_id}/{book_id}.m4b",
                author=author,
                title=title,
            )

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.auto_manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_bulk_revert_unstages_multiple_books(self) -> None:
        class BulkBody:
            book_ids = ["book1", "book2", "book3"]

        bulk_approve(BulkBody())
        result = bulk_revert(BulkBody())

        self.assertEqual(len(result["reverted"]), 3)
        self.assertEqual(result["errors"], [])
        for book_id in ("book1", "book2", "book3"):
            row = self.conn.execute(
                "SELECT status, staged_path FROM books WHERE id = ?", (book_id,)
            ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["staged_path"], "")


if __name__ == "__main__":
    unittest.main()
