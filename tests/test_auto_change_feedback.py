from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.activity_lock import renew_activity_lock
import app.main
from app.api import AutoDismissBody, dismiss_auto_review, get_auto_feedback, holder, revert_book
from app.db import _utcnow, connect, record_auto_change_feedback
from app.scan import ScanManager


def _seed_book_and_action(
    conn,
    *,
    book_id: str = "book1",
    action_id: str = "action1",
    run_id: str = "run1",
    author: str = "Jane Author",
    title: str = "Great Book",
    confidence: float = 0.95,
    min_confidence: float = 0.9,
) -> None:
    now = _utcnow()
    files = [{"name": "book.m4b", "source": "seed/book/book.m4b", "size_bytes": 100}]
    tags = {
        "title": title,
        "album": title,
        "artist": author,
        "albumartist": author,
        "asin": "",
        "narrator": "",
        "raw": {},
    }
    candidates = [
        {
            "author": author,
            "title": title,
            "source": "audnexus",
            "confidence": confidence,
            "raw": {"title": title},
        },
        {
            "author": author,
            "title": "Other Title",
            "source": "openlibrary",
            "confidence": 0.6,
            "raw": {},
        },
    ]
    conn.execute(
        """
        INSERT INTO auto_runs (id, status, trigger, started_at)
        VALUES (?, 'completed', 'manual', ?)
        """,
        (run_id, now),
    )
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)
        """,
        (
            book_id,
            "seed/book",
            json.dumps(["seed", "book"]),
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
            f"{author}/{title}",
            json.dumps(tags),
            json.dumps(candidates),
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO auto_actions (
            id, run_id, book_id, action, author, title, confidence,
            staged_path, source_path, created_at, min_confidence
        ) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_id,
            run_id,
            book_id,
            author,
            title,
            confidence,
            f"{author}/{title}",
            "seed/book",
            now,
            min_confidence,
        ),
    )
    conn.commit()


class AutoChangeFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "books"
        self.library_root = self.root / "library"
        self.books_root.mkdir()
        self.library_root.mkdir()

        book_dir = self.books_root / "seed" / "book"
        book_dir.mkdir(parents=True)
        (book_dir / "book.m4b").write_bytes(b"x" * 100)

        author_dir = self.library_root / "Jane Author" / "Great Book"
        author_dir.mkdir(parents=True)
        staged_file = author_dir / "book.m4b"
        staged_file.hardlink_to(book_dir / "book.m4b")

        self.conn = connect(self.root / "test.db")
        renew_activity_lock(self.conn, "test")
        _seed_book_and_action(self.conn)
        holder.conn = self.conn
        holder.manager = ScanManager(self.conn, self.books_root, self.library_root)

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_record_auto_change_feedback_approved(self) -> None:
        feedback_id = record_auto_change_feedback(
            self.conn,
            action_id="action1",
            decision="approved",
        )
        self.assertIsNotNone(feedback_id)

        row = self.conn.execute(
            "SELECT * FROM auto_change_feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()
        self.assertEqual(row["decision"], "approved")
        self.assertEqual(row["winning_source"], "audnexus")
        self.assertEqual(row["min_confidence"], 0.9)
        self.assertEqual(row["staged_author"], "Jane Author")
        self.assertEqual(row["staged_title"], "Great Book")

        search_context = json.loads(row["search_context_json"])
        self.assertEqual(search_context["author"], "Jane Author")
        self.assertIn("title", search_context)

        action = self.conn.execute(
            "SELECT review_outcome FROM auto_actions WHERE id = 'action1'"
        ).fetchone()
        self.assertEqual(action["review_outcome"], "approved")

    def test_record_auto_change_feedback_rejected(self) -> None:
        feedback_id = record_auto_change_feedback(
            self.conn,
            action_id="action1",
            decision="rejected",
        )
        self.assertIsNotNone(feedback_id)
        row = self.conn.execute(
            "SELECT decision, winning_source FROM auto_change_feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()
        self.assertEqual(row["decision"], "rejected")
        self.assertEqual(row["winning_source"], "audnexus")

    def test_record_auto_change_feedback_idempotent(self) -> None:
        first = record_auto_change_feedback(
            self.conn,
            action_id="action1",
            decision="approved",
        )
        second = record_auto_change_feedback(
            self.conn,
            action_id="action1",
            decision="rejected",
        )
        self.assertEqual(first, second)
        count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM auto_change_feedback WHERE action_id = 'action1'"
        ).fetchone()["count"]
        self.assertEqual(count, 1)

    def test_dismiss_auto_review_records_approved_feedback(self) -> None:
        dismiss_auto_review(AutoDismissBody(action_ids=["action1"]))
        row = self.conn.execute(
            "SELECT decision FROM auto_change_feedback WHERE action_id = 'action1'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["decision"], "approved")
        action = self.conn.execute(
            "SELECT dismissed_at, review_outcome FROM auto_actions WHERE id = 'action1'"
        ).fetchone()
        self.assertIsNotNone(action["dismissed_at"])
        self.assertEqual(action["review_outcome"], "approved")

    def test_revert_book_records_rejected_feedback(self) -> None:
        revert_book("book1")
        row = self.conn.execute(
            "SELECT decision FROM auto_change_feedback WHERE action_id = 'action1'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["decision"], "rejected")
        action = self.conn.execute(
            "SELECT review_outcome FROM auto_actions WHERE id = 'action1'"
        ).fetchone()
        self.assertEqual(action["review_outcome"], "rejected")

    def test_get_auto_feedback_filters_and_parses_json(self) -> None:
        record_auto_change_feedback(
            self.conn,
            action_id="action1",
            decision="approved",
        )
        self.conn.commit()

        result = get_auto_feedback(decision="approved", limit=10, offset=0)
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["decision"], "approved")
        self.assertEqual(item["winning_source"], "audnexus")
        self.assertIsInstance(item["tags"], dict)
        self.assertIsInstance(item["candidates"], list)
        self.assertIsInstance(item["search_context"], dict)
        self.assertIsInstance(item["files"], list)

        empty = get_auto_feedback(decision="rejected")
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["items"], [])


if __name__ == "__main__":
    unittest.main()
