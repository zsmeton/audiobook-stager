from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db import connect, save_conflict_resolution
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.discovery import AudioFile, FlatBook, discover_books
from stager_core.metadata.types import TagInfo
from stager_core.staging import build_inode_index


def _flat_book(book_id: str, source_path: str, file_count: int = 3) -> FlatBook:
    files = [
        AudioFile(
            name=f"{i:02d}.mp3",
            source=f"{source_path}/{i:02d}.mp3",
            size_bytes=10,
        )
        for i in range(1, file_count + 1)
    ]
    return FlatBook(
        id=book_id,
        flatten_name="book",
        source_path=source_path,
        source_path_parts=source_path.split("/"),
        top_level_pack="seed",
        parent_context="",
        grouping="folder",
        files=files,
        flatten_target="book",
    )


class ScanPruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()
        self.conn = connect(self.root / "test.db")
        self.session = StagingSession(self.books, self.library)
        self.scan_manager = ScanManager(
            self.conn, self.books, self.library, self.session
        )
        self.scan_manager.lookup.lookup_book = lambda *a, **k: ([], TagInfo())

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _insert_row(
        self,
        book: FlatBook,
        status: str = "partial_staged",
        *,
        scan_id: str = "scan1",
        staged_path: str = "",
        chosen_author: str = "",
        chosen_title: str = "",
        suggested_author: str = "",
        suggested_title: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO books (
                id, scan_id, source_path, source_path_parts, top_level_pack, parent_context,
                grouping, flatten_name, flatten_target, files_json, status,
                suggested_author, suggested_title, chosen_author, chosen_title,
                confidence, staged_path,
                tags_json, candidates_json, lookup_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                book.id,
                scan_id,
                book.source_path,
                json.dumps(book.source_path_parts),
                book.top_level_pack,
                book.parent_context,
                book.grouping,
                book.flatten_name,
                book.flatten_target,
                json.dumps(
                    [
                        {
                            "name": f.name,
                            "source": f.source,
                            "size_bytes": f.size_bytes,
                        }
                        for f in book.files
                    ]
                ),
                status,
                suggested_author,
                suggested_title or book.flatten_name,
                chosen_author,
                chosen_title,
                0.0,
                staged_path,
                "{}",
                "[]",
                "ok",
            ),
        )
        self.conn.commit()

    def test_prune_removes_orphan_pending_not_in_discovery(self) -> None:
        path = "seed/book"
        orphan = _flat_book("orphan123456", path, 2)
        discovered = _flat_book("discovered12", path, 5)
        self._insert_row(orphan, status="pending")
        self._insert_row(discovered, status="pending")

        self.scan_manager._prune_orphan_books([discovered])

        rows = self.conn.execute("SELECT id FROM books ORDER BY id").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "discovered12")

    def test_prune_removes_stale_staged_orphan(self) -> None:
        path = "seed/staged-book"
        orphan = _flat_book("oldstaged123", path, 2)
        discovered = _flat_book("newpending12", path, 5)
        self._insert_row(orphan, status="staged", staged_path="Author/Title")
        self._insert_row(discovered, status="staged", scan_id="scan2", staged_path="Author/Title")

        self.scan_manager._prune_orphan_books([discovered])

        rows = self.conn.execute(
            "SELECT id, status FROM books WHERE source_path = ? ORDER BY id",
            (path,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "newpending12")

    def test_prune_migrates_chosen_metadata_to_successor(self) -> None:
        path = "seed/staged-book"
        orphan = _flat_book("oldstaged123", path, 2)
        discovered = _flat_book("newpending12", path, 5)
        self._insert_row(
            orphan,
            status="staged",
            staged_path="Author/Title",
            chosen_author="Jane Author",
            chosen_title="Great Book",
        )
        self.conn.execute(
            """
            UPDATE books SET
                chosen_author_set = 1, chosen_title_set = 1,
                suggested_series = 'The Saga', suggested_series_index = '1',
                chosen_series = 'The Saga', chosen_series_set = 1
            WHERE id = ?
            """,
            (orphan.id,),
        )
        self.conn.commit()
        self._insert_row(
            discovered,
            status="staged",
            scan_id="scan2",
            staged_path="Author/Title",
        )

        self.scan_manager._prune_orphan_books([discovered])

        row = self.conn.execute(
            """
            SELECT chosen_author, chosen_title, chosen_author_set, chosen_title_set,
                   suggested_series, chosen_series, chosen_series_set
            FROM books WHERE id = ?
            """,
            ("newpending12",),
        ).fetchone()
        self.assertEqual(row["chosen_author"], "Jane Author")
        self.assertEqual(row["chosen_title"], "Great Book")
        self.assertEqual(int(row["chosen_author_set"] or 0), 1)
        self.assertEqual(int(row["chosen_title_set"] or 0), 1)
        self.assertEqual(row["suggested_series"], "The Saga")
        self.assertEqual(row["chosen_series"], "The Saga")
        self.assertEqual(int(row["chosen_series_set"] or 0), 1)

    def test_prune_migrates_skip_status_to_pending_successor(self) -> None:
        path = "seed/skipped-book"
        orphan = _flat_book("oldskipped1", path, 1)
        discovered = _flat_book("newpending12", path, 1)
        self._insert_row(orphan, status="skipped")
        self._insert_row(discovered, status="pending", scan_id="scan2")

        self.scan_manager._prune_orphan_books([discovered])

        row = self.conn.execute(
            "SELECT status FROM books WHERE id = ?",
            ("newpending12",),
        ).fetchone()
        self.assertEqual(row["status"], "skipped")

    def test_prune_preserves_conflict_resolutions(self) -> None:
        path = "seed/staged-book"
        orphan = _flat_book("oldstaged123", path, 2)
        discovered = _flat_book("newpending12", path, 5)
        self._insert_row(orphan, status="staged", staged_path="Author/Title")
        self._insert_row(
            discovered,
            status="staged",
            scan_id="scan2",
            staged_path="Author/Title",
        )
        save_conflict_resolution(self.conn, "Author/Title", "seed:oldstaged123")

        self.scan_manager._prune_orphan_books([discovered])

        row = self.conn.execute(
            "SELECT winner_side FROM conflict_resolutions WHERE target_key = ?",
            ("Author/Title",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["winner_side"], "seed:oldstaged123")

    def test_prune_keeps_all_split_file_discovery_ids(self) -> None:
        path = "seed/king-of-thorns"
        part1 = _flat_book("splitpart001", path, 1)
        part2 = _flat_book("splitpart002", path, 1)
        self._insert_row(part1, status="pending")
        self._insert_row(part2, status="pending")

        self.scan_manager._prune_orphan_books([part1, part2])

        rows = self.conn.execute(
            "SELECT id FROM books WHERE source_path = ? ORDER BY id",
            (path,),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"splitpart001", "splitpart002"})


class FingerprintRescanPruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()

        book_dir = self.books / "seed" / "Great Book"
        book_dir.mkdir(parents=True)
        self.source_file = book_dir / "book.m4b"
        self.source_file.write_bytes(b"audio-bytes-v1")

        self.conn = connect(self.root / "test.db")
        self.session = StagingSession(self.books, self.library)
        self.scan_manager = ScanManager(
            self.conn, self.books, self.library, self.session
        )
        self.scan_manager.lookup.lookup_book = lambda *a, **k: ([], TagInfo())

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_fingerprint_rescan_prunes_old_staged_row(self) -> None:
        import os

        target_dir = self.library / "Jane Author" / "Great Book"
        target_dir.mkdir(parents=True)
        os.link(self.source_file, target_dir / "book.m4b")

        books_v1 = discover_books(self.books)
        self.assertEqual(len(books_v1), 1)
        book_v1 = books_v1[0]
        inode_index = build_inode_index(self.library)
        self.scan_manager._upsert_book("scan1", book_v1, inode_index)
        self._set_chosen(book_v1.id, "Jane Author", "Great Book")

        self.source_file.write_bytes(b"audio-bytes-v2")
        books_v2 = discover_books(self.books)
        self.assertEqual(len(books_v2), 1)
        book_v2 = books_v2[0]
        self.assertNotEqual(book_v1.id, book_v2.id)

        inode_index = build_inode_index(self.library)
        self.scan_manager._upsert_book("scan2", book_v2, inode_index)
        self.scan_manager._prune_orphan_books(books_v2)

        rows = self.conn.execute(
            "SELECT id, chosen_author, chosen_title, status FROM books"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], book_v2.id)
        self.assertEqual(rows[0]["status"], "staged")
        self.assertEqual(rows[0]["chosen_author"], "Jane Author")
        self.assertEqual(rows[0]["chosen_title"], "Great Book")

    def _set_chosen(self, book_id: str, author: str, title: str) -> None:
        self.conn.execute(
            """
            UPDATE books SET
                chosen_author = ?, chosen_title = ?,
                chosen_author_set = 1, chosen_title_set = 1,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (author, title, book_id),
        )
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
