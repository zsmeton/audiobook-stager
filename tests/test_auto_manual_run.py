from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.activity_lock import renew_activity_lock
from app.auto import AutoRunBlocked, AutoRunManager
from app.db import connect, update_auto_settings
from app.scan import ScanManager


class AutoManualRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")
        self.books = Path(self.tmp.name) / "books"
        self.library = Path(self.tmp.name) / "library"
        self.books.mkdir()
        self.library.mkdir()
        self.scan_manager = ScanManager(self.conn, self.books, self.library)
        self.auto_manager = AutoRunManager(self.conn, self.scan_manager)
        renew_activity_lock(self.conn, "approve")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _mock_thread(self) -> MagicMock:
        thread = MagicMock()
        thread.is_alive.return_value = True
        return thread

    def test_manual_run_bypasses_activity_lock(self) -> None:
        update_auto_settings(self.conn, enabled=False)
        with patch("app.auto.threading.Thread") as mock_thread_cls:
            mock_thread_cls.return_value = self._mock_thread()
            run_id = self.auto_manager.start_run(
                trigger="manual",
                require_enabled=False,
                bypass_activity_lock=True,
            )
        row = self.auto_manager.get_running_run()
        self.assertIsNotNone(row)
        self.assertEqual(run_id, row["id"])
        self.assertEqual(row["trigger"], "manual")

    def test_manual_run_without_bypass_blocked_by_lock(self) -> None:
        with self.assertRaises(AutoRunBlocked) as ctx:
            self.auto_manager.start_run(
                trigger="manual",
                require_enabled=False,
                bypass_activity_lock=False,
            )
        self.assertIn("activity lock", str(ctx.exception).lower())

    def test_scheduled_run_blocked_by_activity_lock(self) -> None:
        update_auto_settings(self.conn, enabled=True)
        with self.assertRaises(AutoRunBlocked) as ctx:
            self.auto_manager.start_run(trigger="scheduled", require_enabled=True)
        self.assertIn("activity", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
