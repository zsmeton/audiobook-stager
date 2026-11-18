from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.activity_lock import get_activity_lock, is_activity_lock_active, renew_activity_lock
from app.db import connect, get_auto_settings, update_auto_settings


class ActivityLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_renew_makes_lock_active(self) -> None:
        renew_activity_lock(self.conn, "approve")
        self.assertTrue(is_activity_lock_active(self.conn))
        lock = get_activity_lock(self.conn)
        self.assertEqual(lock["last_reason"], "approve")

    def test_lock_expires(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.conn.execute(
            "UPDATE activity_lock SET locked_until = ?, last_renewed_at = ? WHERE id = 'default'",
            (past, past),
        )
        self.conn.commit()
        self.assertFalse(is_activity_lock_active(self.conn))

    def test_default_timeout_from_settings(self) -> None:
        settings = get_auto_settings(self.conn)
        self.assertEqual(settings["lock_timeout_minutes"], 15)


if __name__ == "__main__":
    unittest.main()
