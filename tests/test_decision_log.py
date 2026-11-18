from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app.main
from app.api import (
    BookPatch,
    approve_book,
    holder,
    patch_book,
    revert_book,
    skip_book,
)
from app.db import _utcnow, connect, insert_lookup_decision
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.scoring import Evidence, pick_winner


def _insert_pending_book(
    conn,
    book_id: str,
    *,
    status: str = "pending",
    author: str = "Jane Author",
    title: str = "Great Book",
    confidence: float = 0.95,
) -> None:
    files = [{"name": "book.m4b", "source": "seed/book/book.m4b", "size_bytes": 9}]
    candidates = [
        {
            "author": author,
            "title": title,
            "source": "audnexus",
            "confidence": confidence,
            "score_breakdown": {"representative": {"source": "audnexus"}},
        }
    ]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '{}', ?, 'ok', ?)
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
            status,
            author,
            title,
            author,
            title,
            confidence,
            json.dumps(candidates),
            _utcnow(),
        ),
    )
    conn.commit()


class LookupDecisionRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_resolve_writes_one_decision_row(self) -> None:
        # Winner cluster is local-only (id3 + folder agree) -> raw noisy-OR is
        # well above the 0.65 local-only cap, so raw != final. A losing external
        # source (openlibrary, different book) seeds a separate cluster.
        evidence = [
            Evidence(source="id3", author="Pierce Brown", title="Red Rising"),
            Evidence(source="folder", author="Pierce Brown", title="Red Rising"),
            Evidence(source="openlibrary", author="Frank Herbert", title="Dune"),
        ]
        _, breakdown = pick_winner(evidence)

        insert_lookup_decision(
            self.conn,
            book_id="book1",
            scan_id="scan1",
            trigger="scan",
            breakdown=breakdown,
            search_context={"title": "Red Rising", "author": "Pierce Brown"},
            tags={"title": "Red Rising"},
        )

        rows = self.conn.execute(
            "SELECT * FROM lookup_decisions WHERE book_id = 'book1'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["trigger"], "scan")
        self.assertEqual(row["scan_id"], "scan1")
        self.assertEqual(row["winning_source"], "id3")
        # raw (pre-cap) is strictly above final (post local-only cap).
        self.assertGreater(row["raw_confidence"], row["confidence"])
        self.assertEqual(row["confidence"], 0.65)

        families = json.loads(row["families_json"])
        self.assertIn("tags", families)
        self.assertIn("path", families)

        caps = json.loads(row["caps_applied"])
        self.assertTrue(any("local_only" in c for c in caps))

        evidence_pool = json.loads(row["evidence_json"])
        sources = {e["source"] for e in evidence_pool}
        # Full pool retains the losing source.
        self.assertIn("openlibrary", sources)
        self.assertIn("id3", sources)

    def test_no_match_writes_row_with_empty_pool(self) -> None:
        _, breakdown = pick_winner([])
        insert_lookup_decision(
            self.conn,
            book_id="book2",
            trigger="manual_relookup",
            breakdown=breakdown,
        )
        row = self.conn.execute(
            "SELECT * FROM lookup_decisions WHERE book_id = 'book2'"
        ).fetchone()
        self.assertEqual(row["status"], "no_match")
        self.assertEqual(json.loads(row["evidence_json"]), [])


class DecisionOutcomeTests(unittest.TestCase):
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
        holder.conn = self.conn
        holder.manager = self.scan_manager

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def _get_outcome(self, book_id: str, action: str):
        return self.conn.execute(
            "SELECT * FROM decision_outcomes WHERE book_id = ? AND action = ?",
            (book_id, action),
        ).fetchone()

    def test_approve_writes_outcome(self) -> None:
        _insert_pending_book(self.conn, "book1")
        approve_book("book1")
        row = self._get_outcome("book1", "approve")
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Great Book")
        self.assertEqual(row["confidence_at_action"], 0.95)
        self.assertEqual(row["winning_source_at_action"], "audnexus")

    def test_skip_writes_outcome(self) -> None:
        _insert_pending_book(self.conn, "book1")
        skip_book("book1")
        row = self._get_outcome("book1", "skip")
        self.assertIsNotNone(row)
        self.assertEqual(row["author"], "Jane Author")

    def test_revert_writes_outcome(self) -> None:
        _insert_pending_book(self.conn, "book1")
        approve_book("book1")
        revert_book("book1")
        row = self._get_outcome("book1", "revert")
        self.assertIsNotNone(row)

    def test_edit_metadata_writes_outcome_with_prev(self) -> None:
        _insert_pending_book(self.conn, "book1")
        patch_book("book1", BookPatch(chosen_author="New Author", chosen_title="New Title"))
        row = self._get_outcome("book1", "edit_metadata")
        self.assertIsNotNone(row)
        self.assertEqual(row["prev_author"], "Jane Author")
        self.assertEqual(row["prev_title"], "Great Book")
        self.assertEqual(row["author"], "New Author")
        self.assertEqual(row["title"], "New Title")

    def test_decision_joins_to_outcome_by_book_id(self) -> None:
        _insert_pending_book(self.conn, "book1")
        insert_lookup_decision(
            self.conn,
            book_id="book1",
            scan_id="scan1",
            trigger="scan",
            breakdown={
                "status": "ok",
                "confidence": 0.95,
                "raw_confidence": 0.97,
                "cluster_size": 1,
                "representative": {"source": "audnexus", "author": "Jane Author", "title": "Great Book"},
                "families": {},
                "evidence_pool": [],
            },
        )
        skip_book("book1")
        joined = self.conn.execute(
            """
            SELECT d.book_id AS d_book, o.book_id AS o_book,
                   d.winning_source AS d_source, o.action AS o_action
            FROM lookup_decisions d
            JOIN decision_outcomes o ON o.book_id = d.book_id
            WHERE d.book_id = 'book1'
            """
        ).fetchall()
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0]["d_book"], joined[0]["o_book"])
        self.assertEqual(joined[0]["d_source"], "audnexus")
        self.assertEqual(joined[0]["o_action"], "skip")


class ScanSkipNoDecisionTests(unittest.TestCase):
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
        self.scan_manager = ScanManager(self.conn, self.books, self.library)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _flatbook(self) -> FlatBook:
        return FlatBook(
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

    def test_skipped_book_routine_scan_writes_no_decision(self) -> None:
        _insert_pending_book(self.conn, "book1", status="skipped")
        # Routine scan re-visits the skipped book; the lookup policy skips the
        # network entirely, so no decision row should be written.
        self.scan_manager._upsert_book("scan2", self._flatbook(), {})
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM lookup_decisions WHERE book_id = 'book1'"
        ).fetchone()["n"]
        self.assertEqual(count, 0)
        # Sanity: the book stays skipped.
        status = self.conn.execute(
            "SELECT status FROM books WHERE id = 'book1'"
        ).fetchone()["status"]
        self.assertEqual(status, "skipped")


if __name__ == "__main__":
    unittest.main()
