from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.main
from app.api import get_session_status, holder
from app.db import _utcnow, connect, update_session_meta
from app.scan import ScanManager
from app.session import StagingSession


class SessionStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.library_root = self.root / "lib"
        self.books_root.mkdir()
        self.library_root.mkdir()
        self.conn = connect(self.root / "test.db")
        holder.conn = self.conn
        holder.session = StagingSession(self.books_root, self.library_root)
        holder.session.stale = True
        holder.manager = ScanManager(
            self.conn, self.books_root, self.library_root, holder.session
        )
        holder.auto_manager = None

    def tearDown(self) -> None:
        holder.conn = None
        holder.manager = None
        holder.auto_manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_no_scan_state(self) -> None:
        status = get_session_status()
        self.assertEqual(status["state"], "no_scan")
        self.assertTrue(status["needs_scan"])

    def test_fresh_state_after_recent_scan(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO scans (id, status, started_at, finished_at, total_books, metadata_done, message)
            VALUES ('s1', 'completed', ?, ?, 1, 1, 'done')
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO books (
                id, scan_id, source_path, source_path_parts, files_json, status, updated_at
            ) VALUES ('b1', 's1', 'seed', '["seed"]', '[]', 'pending', ?)
            """,
            (_utcnow(),),
        )
        self.conn.commit()
        holder.session.rebuild_target_indexes("s1")
        holder.session.persist_scan_snapshot(self.conn, scan_id="s1", source_book_count=1)
        update_session_meta(
            self.conn,
            last_scan_finished_at=now,
            last_source_discovery_at=now,
        )
        status = get_session_status()
        self.assertEqual(status["state"], "fresh")
        self.assertFalse(status["needs_scan"])
        self.assertTrue(status["session_hydrated"])

    def test_recent_scan_without_hydration_needs_scan(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO scans (id, status, started_at, finished_at, total_books, metadata_done, message)
            VALUES ('s1', 'completed', ?, ?, 1, 1, 'done')
            """,
            (now, now),
        )
        self.conn.execute(
            """
            INSERT INTO books (
                id, scan_id, source_path, source_path_parts, files_json, status, updated_at
            ) VALUES ('b1', 's1', 'seed', '["seed"]', '[]', 'pending', ?)
            """,
            (_utcnow(),),
        )
        self.conn.commit()
        update_session_meta(
            self.conn,
            last_scan_finished_at=now,
            last_source_discovery_at=now,
            source_book_count=1,
        )
        holder.session.stale = True
        holder.session.session_ready = False
        status = get_session_status()
        self.assertEqual(status["state"], "stale_scan")
        self.assertTrue(status["needs_scan"])
        self.assertFalse(status["session_hydrated"])

    def test_stale_scan_state(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self.conn.execute(
            """
            INSERT INTO scans (id, status, started_at, finished_at, total_books, metadata_done, message)
            VALUES ('s1', 'completed', ?, ?, 1, 1, 'done')
            """,
            (old, old),
        )
        self.conn.commit()
        update_session_meta(self.conn, last_scan_finished_at=old, last_source_discovery_at=old)
        status = get_session_status()
        self.assertEqual(status["state"], "stale_scan")
        self.assertTrue(status["needs_scan"])


if __name__ == "__main__":
    unittest.main()
