from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main
from app.api import approve_book, holder
from app.auto import AutoRunManager
from app.db import _utcnow, connect
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.discovery import AudioFile, FlatBook
from stager_core.staging import stage_book_author_title


def _insert_pending_book(
    conn,
    book_id: str,
    *,
    author: str = "Jane Author",
    title: str = "Great Book",
    confidence: float = 0.95,
) -> None:
    files = [{"name": "book.m4b", "source": "seed/book/book.m4b", "size_bytes": 9}]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, '', '{}', '[]', 'ok', ?)
        """,
        (
            book_id,
            "seed/book",
            '["seed","book"]',
            "seed",
            "",
            "folder",
            "book",
            "book",
            json.dumps(files),
            author,
            title,
            author,
            title,
            confidence,
            _utcnow(),
        ),
    )
    conn.commit()


class ManualApproveReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()
        book_dir = self.books / "seed" / "book"
        book_dir.mkdir(parents=True)
        (book_dir / "book.m4b").write_bytes(b"audio-data")

        self.conn = connect(self.root / "test.db")
        holder.session = StagingSession(self.books, self.library)
        holder.session.rebuild_target_indexes()
        self.scan_manager = ScanManager(self.conn, self.books, self.library, holder.session)
        self.auto_manager = AutoRunManager(self.conn, self.scan_manager, holder.session)
        holder.conn = self.conn
        holder.manager = self.scan_manager
        holder.auto_manager = self.auto_manager

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.auto_manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_approve_dismisses_existing_auto_action(self) -> None:
        _insert_pending_book(self.conn, "book1")
        self.conn.execute(
            """
            INSERT INTO auto_runs (id, status, trigger, started_at)
            VALUES ('run1', 'completed', 'scheduled', ?)
            """,
            (_utcnow(),),
        )
        self.conn.execute(
            """
            INSERT INTO auto_actions (
                id, run_id, book_id, action, author, title, confidence,
                staged_path, source_path, created_at, min_confidence
            ) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "action1",
                "run1",
                "book1",
                "Jane Author",
                "Great Book",
                0.95,
                "Jane Author/Great Book",
                "seed/book",
                _utcnow(),
                0.9,
            ),
        )
        self.conn.commit()

        approve_book("book1")

        row = self.conn.execute(
            "SELECT dismissed_at FROM auto_actions WHERE id = 'action1'"
        ).fetchone()
        self.assertIsNotNone(row["dismissed_at"])

    def test_auto_run_does_not_queue_manually_staged_book(self) -> None:
        _insert_pending_book(self.conn, "book1")
        book = FlatBook(
            id="book1",
            flatten_name="book",
            source_path="seed/book",
            source_path_parts=["seed", "book"],
            top_level_pack="seed",
            parent_context="",
            grouping="folder",
            files=[AudioFile(name="book.m4b", source="seed/book/book.m4b", size_bytes=9)],
            flatten_target="book",
        )
        staged = stage_book_author_title(
            self.books,
            self.library,
            book,
            "Jane Author",
            "Great Book",
            {},
            dry_run=False,
        )
        self.assertEqual(staged.status, "staged")
        self.conn.execute(
            """
            UPDATE books SET status = 'staged', staged_path = ?, updated_at = ?
            WHERE id = 'book1'
            """,
            (staged.target_path, _utcnow()),
        )
        self.conn.commit()

        self.conn.execute(
            """
            INSERT INTO auto_runs (id, status, trigger, started_at, phase)
            VALUES ('run1', 'running', 'scheduled', ?, 'starting')
            """,
            (_utcnow(),),
        )
        self.conn.commit()

        with patch.object(AutoRunManager, "_wait_for_scan", return_value=True):
            with patch.object(ScanManager, "start_scan", return_value="scan1"):
                self.auto_manager._run_auto("run1")

        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM auto_actions WHERE book_id = 'book1'"
        ).fetchone()["n"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
