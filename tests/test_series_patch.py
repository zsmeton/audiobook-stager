from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app.main
from app.api import BookPatch, TargetKeyPreviewBody, holder, patch_book, preview_book_target_key
from app.db import connect, row_to_book
from app.session import StagingSession
from app.scan import ScanManager


def _insert_book(conn, book_id: str = "book1") -> None:
    candidates = [
        {
            "author": "Jane",
            "title": "Book One",
            "source": "audnexus",
            "confidence": 0.9,
            "in_winning_cluster": True,
            "series_membership": 0.8,
        },
        {
            "author": "Other",
            "title": "Other",
            "source": "mam",
            "confidence": 0.5,
            "in_winning_cluster": False,
        },
    ]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title,
            suggested_series, suggested_series_index, suggested_series_state,
            chosen_author, chosen_title, chosen_series, chosen_series_index,
            chosen_author_set, chosen_title_set, chosen_series_set, chosen_series_index_set,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '{}', ?, 'ok', '2026-01-01')
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
            json.dumps([{"name": "book.m4b", "source": "seed/book/book.m4b", "size_bytes": 1}]),
            "pending",
            "Jane",
            "Book One",
            "The Saga",
            "1",
            "confirmed",
            "",
            "",
            "",
            "",
            0,
            0,
            0,
            0,
            0.8,
            json.dumps(candidates),
        ),
    )
    conn.commit()


class SeriesPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()
        self.conn = connect(self.root / "test.db")
        holder.session = StagingSession(self.books, self.library)
        holder.session.rebuild_target_indexes()
        holder.manager = ScanManager(self.conn, self.books, self.library, holder.session)
        holder.conn = self.conn
        _insert_book(self.conn)

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_patch_empty_series_confirms_none(self) -> None:
        patch_book(
            "book1",
            BookPatch(
                chosen_author="Jane",
                chosen_title="Book One",
                chosen_series="",
                chosen_series_index="",
            ),
        )
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_series_state"], "confirmed_none")
        self.assertEqual(book["chosen_series_set"], 1)
        self.assertEqual(book["target_key_preview"], "Jane/Book One")

    def test_patch_series_and_index(self) -> None:
        patch_book(
            "book1",
            BookPatch(
                chosen_author="Jane",
                chosen_title="Book One",
                chosen_series="The Saga",
                chosen_series_index="2",
            ),
        )
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_series_state"], "confirmed")
        self.assertEqual(book["target_key_preview"], "Jane/The Saga/2 - Book One")

    def test_candidates_expose_series_membership(self) -> None:
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        winner = next(c for c in book["candidates"] if c["in_winning_cluster"])
        self.assertAlmostEqual(winner["series_membership"], 0.8)
        self.assertNotIn("confidence_breakdown", book)

    def test_target_key_preview_endpoint(self) -> None:
        preview = preview_book_target_key(
            "book1",
            TargetKeyPreviewBody(
                chosen_author="Jane",
                chosen_title="Book One",
                chosen_series="",
                chosen_series_index="",
            ),
        )
        self.assertEqual(preview["chosen_series_state"], "confirmed_none")
        self.assertEqual(preview["target_key_preview"], "Jane/Book One")

    def test_patch_empty_series_without_suggestion_does_not_pin(self) -> None:
        self.conn.execute(
            """
            UPDATE books
            SET suggested_series = '', suggested_series_index = ''
            WHERE id = 'book1'
            """
        )
        self.conn.commit()
        patch_book(
            "book1",
            BookPatch(
                chosen_author="Jane",
                chosen_title="Book One",
                chosen_series="",
                chosen_series_index="",
            ),
        )
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_author_set"], 1)
        self.assertEqual(book["chosen_title_set"], 1)
        self.assertEqual(book["chosen_series_set"], 0)
        self.assertEqual(book["chosen_series_index_set"], 0)


if __name__ == "__main__":
    unittest.main()
