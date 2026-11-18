from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import app.main
from app.api import _aggregate_health_status, _run_health_checks, holder
from app.db import DB_LOCK, _utcnow, connect
from app.scan import ScanManager
from app.session import StagingSession


class HealthChecksTests(unittest.TestCase):
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

    def test_database_check_ok(self) -> None:
        checks = _run_health_checks()
        self.assertEqual(checks["database"]["status"], "ok")
        self.assertEqual(checks["database"]["integrity"], "ok")
        self.assertIn("lock_wait_ms", checks["database"])
        self.assertEqual(_aggregate_health_status(checks), "ok")

    def test_database_degraded_when_lock_held(self) -> None:
        acquired = threading.Event()
        release = threading.Event()

        def hold_lock() -> None:
            DB_LOCK.acquire()
            acquired.set()
            release.wait(timeout=10)
            DB_LOCK.release()

        thread = threading.Thread(target=hold_lock, daemon=True)
        thread.start()
        self.assertTrue(acquired.wait(timeout=2))

        checks = _run_health_checks()
        release.set()
        thread.join(timeout=2)

        self.assertEqual(checks["database"]["status"], "degraded")
        self.assertIn("DB_LOCK not acquired", checks["database"]["detail"])
        self.assertEqual(_aggregate_health_status(checks), "degraded")

    def test_running_scan_reported(self) -> None:
        now = _utcnow()
        self.conn.execute(
            """
            INSERT INTO scans (
                id, status, started_at, total_books, metadata_done, books_found, message
            )
            VALUES ('scan1', 'running', ?, 0, 0, 42, 'Discovering books… 42 found')
            """,
            (now,),
        )
        self.conn.commit()
        holder.manager._thread = MagicMock()
        holder.manager._thread.is_alive.return_value = True

        checks = _run_health_checks()
        self.assertTrue(checks["scan"]["running"])
        self.assertEqual(checks["scan"]["scan_id"], "scan1")
        self.assertEqual(checks["scan"]["phase"], "discovery")
        self.assertEqual(checks["scan"]["books_found"], 42)
