from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.api import approve_book, holder
from app.db import _utcnow, connect, row_to_book
from app.scan import ScanManager
from app.session import StagingSession


def _insert_series_book(conn, book_id: str = "book1") -> None:
    source_path = "Leigh Bardugo/Six of Crows/1 - Six of Crows"
    files = [
        {
            "name": "book.m4b",
            "source": f"{source_path}/book.m4b",
            "size_bytes": 9,
        }
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '{}', '[]', 'ok', ?)
        """,
        (
            book_id,
            source_path,
            '["Leigh Bardugo","Six of Crows","1 - Six of Crows"]',
            "Leigh Bardugo",
            "Six of Crows",
            "folder",
            "1 - Six of Crows",
            "1 - Six of Crows",
            json.dumps(files),
            "Leigh Bardugo",
            "Six of Crows",
            "Six of Crows",
            "1",
            "confirmed",
            "Leigh Bardugo",
            "Six of Crows",
            "Six of Crows",
            "1",
            1,
            1,
            1,
            1,
            0.95,
            _utcnow(),
        ),
    )
    conn.commit()


class ApproveSeriesMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()
        book_dir = (
            self.books / "Leigh Bardugo" / "Six of Crows" / "1 - Six of Crows"
        )
        book_dir.mkdir(parents=True)
        (book_dir / "book.m4b").write_bytes(b"audio-data")

        self.conn = connect(self.root / "test.db")
        holder.session = StagingSession(self.books, self.library)
        holder.session.rebuild_target_indexes()
        holder.manager = ScanManager(self.conn, self.books, self.library, holder.session)
        holder.conn = self.conn
        _insert_series_book(self.conn)

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_approve_stores_semantic_title_not_path_suffix(self) -> None:
        approve_book("book1")

        row = self.conn.execute("SELECT * FROM books WHERE id = 'book1'").fetchone()
        book = row_to_book(row)
        self.assertEqual(row["chosen_title"], "Six of Crows")
        self.assertEqual(row["chosen_series"], "Six of Crows")
        self.assertEqual(row["chosen_series_index"], "1")
        self.assertEqual(row["staged_path"], "Leigh Bardugo/Six of Crows/1 - Six of Crows")
        self.assertEqual(
            book["target_key_preview"],
            "Leigh Bardugo/Six of Crows/1 - Six of Crows",
        )


if __name__ == "__main__":
    unittest.main()
