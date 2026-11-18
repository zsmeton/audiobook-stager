from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db import connect


def _insert_book(
    conn,
    *,
    book_id: str = "book1",
    chosen_author: str = "Jane",
    suggested_author: str = "Jane",
    chosen_title: str = "Book",
    suggested_title: str = "Book",
    author_set: int = 0,
    title_set: int = 0,
    chosen_series: str = "",
    suggested_series: str = "",
    series_set: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, suggested_series,
            chosen_author, chosen_title, chosen_series,
            chosen_author_set, chosen_title_set, chosen_series_set, chosen_series_index_set,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '{}', '[]', 'ok', '2026-01-01')
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
            suggested_author,
            suggested_title,
            suggested_series,
            chosen_author,
            chosen_title,
            chosen_series,
            author_set,
            title_set,
            series_set,
            0,
            0.8,
        ),
    )
    conn.commit()


class ChosenPinMigrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reconnect_does_not_pin_staging_snapshot(self) -> None:
        conn = connect(self.db_path)
        _insert_book(conn, author_set=0, title_set=0)
        conn.close()

        conn = connect(self.db_path)
        row = conn.execute(
            "SELECT chosen_author_set, chosen_title_set FROM books WHERE id = 'book1'"
        ).fetchone()
        self.assertEqual(int(row["chosen_author_set"] or 0), 0)
        self.assertEqual(int(row["chosen_title_set"] or 0), 0)
        conn.close()

    def test_repair_unpins_chosen_matching_suggested(self) -> None:
        conn = connect(self.db_path)
        _insert_book(conn, author_set=1, title_set=1)
        conn.execute("DELETE FROM schema_flags")
        conn.commit()
        conn.close()

        conn = connect(self.db_path)
        row = conn.execute(
            "SELECT chosen_author_set, chosen_title_set FROM books WHERE id = 'book1'"
        ).fetchone()
        self.assertEqual(int(row["chosen_author_set"] or 0), 0)
        self.assertEqual(int(row["chosen_title_set"] or 0), 0)
        conn.close()

    def test_repair_keeps_divergent_pins(self) -> None:
        conn = connect(self.db_path)
        _insert_book(
            conn,
            chosen_author="Manual Author",
            suggested_author="Jane",
            author_set=1,
            title_set=0,
        )
        conn.execute("DELETE FROM schema_flags")
        conn.commit()
        conn.close()

        conn = connect(self.db_path)
        row = conn.execute(
            "SELECT chosen_author_set, chosen_title_set FROM books WHERE id = 'book1'"
        ).fetchone()
        self.assertEqual(int(row["chosen_author_set"] or 0), 1)
        self.assertEqual(int(row["chosen_title_set"] or 0), 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
