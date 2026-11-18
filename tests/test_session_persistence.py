from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db import _utcnow, connect, count_books, get_session_meta, load_library_targets
from app.session import StagingSession


class SessionPersistenceTests(unittest.TestCase):
    def test_persist_and_hydrate_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library_root = root / "lib"
            books_root = root / "src"
            target = library_root / "Author" / "Title"
            target.mkdir(parents=True)
            (target / "book.mp3").write_bytes(b"x" * 100)
            books_root.mkdir()

            conn = connect(root / "test.db")
            conn.execute(
                """
                INSERT INTO books (
                    id, scan_id, source_path, source_path_parts, files_json, status, updated_at
                ) VALUES ('b1', 'scan1', 'seed', '["seed"]', '[]', 'pending', ?)
                """,
                (_utcnow(),),
            )
            conn.commit()
            try:
                session = StagingSession(books_root, library_root)
                session.rebuild_target_indexes("scan1")
                session.persist_scan_snapshot(conn, scan_id="scan1", source_book_count=1)

                meta = get_session_meta(conn)
                self.assertEqual(meta["last_scan_id"], "scan1")
                self.assertEqual(meta["source_book_count"], 1)
                self.assertGreater(meta["library_target_count"], 0)
                self.assertEqual(len(load_library_targets(conn)), 1)

                hydrated = StagingSession.try_hydrate_from_db(conn, books_root, library_root)
                self.assertIsNotNone(hydrated)
                assert hydrated is not None
                self.assertTrue(hydrated.session_ready)
                self.assertIn("Author/Title", hydrated.library_index)
            finally:
                conn.close()

    def test_hydrate_returns_none_when_no_books(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "test.db")
            session = StagingSession(root / "src", root / "lib")
            session.rebuild_target_indexes("scan1")
            try:
                session = StagingSession(root / "src", root / "lib")
                session.rebuild_target_indexes("scan1")
                session.persist_scan_snapshot(conn, scan_id="scan1", source_book_count=0)
                self.assertEqual(count_books(conn), 0)
                self.assertIsNone(
                    StagingSession.try_hydrate_from_db(conn, root / "src", root / "lib")
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
