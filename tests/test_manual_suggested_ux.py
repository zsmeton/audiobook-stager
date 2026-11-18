from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app.main
from app.api import BookPatch, holder, patch_book
from app.db import connect, row_to_book
from app.session import StagingSession
from app.scan import ScanManager


def _insert_book(conn, *, author_set: int = 0, title_set: int = 0) -> None:
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '{}', '[]', 'ok', '2026-01-01')
        """,
        (
            "book1",
            "seed/book",
            '["seed","book"]',
            "seed",
            "",
            "folder",
            "book",
            "book",
            json.dumps([{"name": "book.m4b", "source": "seed/book/book.m4b", "size_bytes": 1}]),
            "pending",
            "Jane Doe",
            "Suggested Title",
            "The Saga",
            "1",
            "confirmed",
            "Manual Author",
            "Manual Title",
            "Manual Series",
            "2",
            author_set,
            title_set,
            0,
            0,
            0.8,
        ),
    )
    conn.commit()


class ManualSuggestedUxTests(unittest.TestCase):
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
        _insert_book(self.conn, author_set=1, title_set=1)

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_revert_single_field_uses_suggested(self) -> None:
        patch_book("book1", BookPatch(revert_fields=["author"]))
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_author_set"], 0)
        self.assertEqual(book["chosen_title_set"], 1)
        self.assertEqual(book["effective_author"], "Jane Doe")
        self.assertEqual(book["effective_title"], "Manual Title")

    def test_revert_all_clears_manual_flags(self) -> None:
        patch_book("book1", BookPatch(revert_all=True))
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_author_set"], 0)
        self.assertEqual(book["chosen_title_set"], 0)
        self.assertEqual(book["chosen_series_set"], 0)
        self.assertEqual(book["chosen_series_index_set"], 0)
        self.assertEqual(book["effective_author"], "Jane Doe")
        self.assertEqual(book["effective_title"], "Suggested Title")

    def test_save_marks_all_fields_manual(self) -> None:
        self.conn.execute("DELETE FROM books WHERE id = 'book1'")
        self.conn.commit()
        _insert_book(self.conn, author_set=0, title_set=0)
        patch_book(
            "book1",
            BookPatch(
                chosen_author="New Author",
                chosen_title="New Title",
                chosen_series="",
                chosen_series_index="",
            ),
        )
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_author_set"], 1)
        self.assertEqual(book["chosen_title_set"], 1)
        self.assertEqual(book["chosen_series_set"], 1)
        self.assertEqual(book["chosen_series_index_set"], 1)

    def test_revert_then_save_stays_manual(self) -> None:
        patch_book("book1", BookPatch(revert_fields=["author"]))
        patch_book(
            "book1",
            BookPatch(
                chosen_author="Edited Author",
                chosen_title="Manual Title",
                chosen_series="Manual Series",
                chosen_series_index="2",
            ),
        )
        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(book["chosen_author_set"], 1)
        self.assertEqual(book["effective_author"], "Edited Author")


if __name__ == "__main__":
    unittest.main()
