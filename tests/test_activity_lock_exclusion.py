from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import app.main
from app.api import holder, start_scan
from app.auto import AutoRunBlocked, AutoRunManager
from app.db import _utcnow, connect


class ActivityLockExclusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")

    def tearDown(self) -> None:
        holder.manager = None
        holder.auto_manager = None
        holder.conn = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def _alive_thread(self) -> MagicMock:
        thread = MagicMock()
        thread.is_alive.return_value = True
        return thread

    def test_running_auto_blocks_manual_scan(self) -> None:
        auto = AutoRunManager(self.conn, MagicMock())
        self.conn.execute(
            """
            INSERT INTO auto_runs (id, status, trigger, started_at, phase, message)
            VALUES ('run1', 'running', 'scheduled', ?, 'scanning', '')
            """,
            (_utcnow(),),
        )
        self.conn.commit()
        auto._thread = self._alive_thread()
        self.assertTrue(auto.is_running())

        holder.conn = self.conn
        holder.manager = MagicMock()
        holder.auto_manager = auto
        with self.assertRaises(HTTPException) as ctx:
            start_scan()

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["kind"], "auto_run")
        self.assertEqual(ctx.exception.detail["auto_run_id"], "run1")
        self.assertEqual(
            ctx.exception.detail["message"],
            "Auto-scan and stage in progress",
        )
        holder.manager.start_scan.assert_not_called()

    def test_live_scan_thread_blocks_auto_run(self) -> None:
        scan = MagicMock()
        scan.get_running_scan.return_value = {"id": "scan1"}
        scan._thread = self._alive_thread()
        auto = AutoRunManager(self.conn, scan)

        with self.assertRaises(AutoRunBlocked) as ctx:
            auto.start_run(
                trigger="scheduled",
                require_enabled=False,
                bypass_activity_lock=True,
            )

        self.assertEqual(str(ctx.exception), "manual scan already in progress")
        count = self.conn.execute("SELECT COUNT(*) AS c FROM auto_runs").fetchone()
        self.assertEqual(count["c"], 0)

    def test_scan_row_without_live_thread_does_not_block_auto(self) -> None:
        scan = MagicMock()
        scan.get_running_scan.return_value = {"id": "scan1"}
        scan._thread = MagicMock()
        scan._thread.is_alive.return_value = False
        auto = AutoRunManager(self.conn, scan)

        with patch("app.auto.threading.Thread") as thread_cls:
            thread_cls.return_value = self._alive_thread()
            run_id = auto.start_run(
                trigger="manual",
                require_enabled=False,
                bypass_activity_lock=True,
            )

        row = auto.get_running_run()
        self.assertIsNotNone(row)
        self.assertEqual(run_id, row["id"])
        self.assertEqual(row["trigger"], "manual")
