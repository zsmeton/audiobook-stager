from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main
from app.api import cancel_scan, holder
from app.db import connect
from app.scan import ScanManager
from stager_core.conflicts import build_library_index
from stager_core.discovery import DiscoveryCancelled, discover_books
from stager_core.target_index import build_target_indexes


class ScanCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.library_root = self.root / "lib"
        self.books_root.mkdir()
        self.library_root.mkdir()
        self.conn = connect(self.root / "test.db")
        self.manager = ScanManager(self.conn, self.books_root, self.library_root)

    def tearDown(self) -> None:
        if self.manager._thread and self.manager._thread.is_alive():
            row = self.manager.get_running_scan()
            if row:
                self.manager.cancel_scan(row["id"])
            self.manager._thread.join(timeout=5)
        self.conn.close()
        self.tmp.cleanup()

    def test_cancel_marks_scan_cancelled(self) -> None:
        def slow_discover(
            _root,
            *,
            on_progress=None,
            progress_interval=50,
            should_cancel=None,
            fingerprint_cache=None,
        ):
            for i in range(1, 101):
                if should_cancel and should_cancel():
                    raise DiscoveryCancelled()
                if on_progress:
                    on_progress(i)
                time.sleep(0.02)
            return []

        with patch("app.scan.discover_books", side_effect=slow_discover):
            scan_id = self.manager.start_scan()
            time.sleep(0.15)
            self.assertTrue(self.manager.cancel_scan(scan_id))
            deadline = time.time() + 2
            row = None
            while time.time() < deadline:
                row = self.conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
                if row and row["status"] == "cancelled":
                    break
                time.sleep(0.05)
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "cancelled")

    def test_cancel_sets_cancelling_message_before_finish(self) -> None:
        release = threading.Event()

        def slow_discover(
            _root,
            *,
            on_progress=None,
            progress_interval=50,
            should_cancel=None,
            fingerprint_cache=None,
        ):
            for i in range(1, 101):
                if should_cancel and should_cancel():
                    release.wait(timeout=3)
                    raise DiscoveryCancelled()
                if on_progress:
                    on_progress(i)
                time.sleep(0.05)
            return []

        with patch("app.scan.discover_books", side_effect=slow_discover):
            scan_id = self.manager.start_scan()
            time.sleep(0.1)
            self.manager.cancel_scan(scan_id)
            row = self.conn.execute("SELECT message FROM scans WHERE id = ?", (scan_id,)).fetchone()
            self.assertIn("Cancelling", row["message"])
            release.set()
            self.manager._thread.join(timeout=3)

    def test_cancel_during_index_phase_marks_cancelled(self) -> None:
        index_started = threading.Event()

        def slow_index(
            _root,
            *,
            should_cancel=None,
            cancel_check_interval=500,
            on_progress=None,
            progress_interval=50,
            workers=None,
        ):
            index_started.set()
            for _ in range(50):
                if should_cancel and should_cancel():
                    raise DiscoveryCancelled()
                time.sleep(0.02)
            return {}, {}

        with patch("app.scan.discover_books", return_value=[]):
            with patch(
                "app.scan.build_target_indexes",
                side_effect=slow_index,
            ):
                scan_id = self.manager.start_scan()
                self.assertTrue(index_started.wait(timeout=2))
                self.assertTrue(self.manager.cancel_scan(scan_id))
                deadline = time.time() + 2
                row = None
                while time.time() < deadline:
                    row = self.conn.execute(
                        "SELECT * FROM scans WHERE id = ?", (scan_id,)
                    ).fetchone()
                    if row and row["status"] == "cancelled":
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "cancelled")

    def test_indexing_phase_keeps_discovery_animation(self) -> None:
        index_entered = threading.Event()

        def slow_index(
            _root,
            *,
            should_cancel=None,
            cancel_check_interval=500,
            on_progress=None,
            progress_interval=50,
            workers=None,
        ):
            index_entered.set()
            time.sleep(0.15)
            return {}, {}

        with patch("app.scan.discover_books", return_value=[]):
            with patch(
                "app.scan.build_target_indexes",
                side_effect=slow_index,
            ):
                scan_id = self.manager.start_scan()
                self.assertTrue(index_entered.wait(timeout=2))
                row = self.conn.execute(
                    "SELECT scan_phase, total_books FROM scans WHERE id = ?", (scan_id,)
                ).fetchone()
                self.assertEqual(row["scan_phase"], "discovering")
                self.assertEqual(row["total_books"], 0)
                self.manager.cancel_scan(scan_id)
                self.manager._thread.join(timeout=3)


class ScanCancelApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.library_root = self.root / "lib"
        self.books_root.mkdir()
        self.library_root.mkdir()
        self.conn = connect(self.root / "test.db")
        self.manager = ScanManager(self.conn, self.books_root, self.library_root)
        holder.conn = self.conn
        holder.manager = self.manager

    def tearDown(self) -> None:
        if self.manager._thread and self.manager._thread.is_alive():
            row = self.manager.get_running_scan()
            if row:
                self.manager.cancel_scan(row["id"])
            self.manager._thread.join(timeout=5)
        holder.conn = None
        holder.manager = None
        self.conn.close()
        self.tmp.cleanup()

    def test_cancel_api_returns_cancelling_message(self) -> None:
        def slow_discover(
            _root,
            *,
            on_progress=None,
            progress_interval=50,
            should_cancel=None,
            fingerprint_cache=None,
        ):
            for i in range(1, 101):
                if should_cancel and should_cancel():
                    raise DiscoveryCancelled()
                if on_progress:
                    on_progress(i)
                time.sleep(0.05)
            return []

        with patch("app.scan.discover_books", side_effect=slow_discover):
            scan_id = self.manager.start_scan()
            time.sleep(0.1)
            result = cancel_scan(scan_id)
            self.assertTrue(result["cancelled"])
            self.assertIn("Cancelling", result["message"])
            self.manager._thread.join(timeout=3)


class IndexCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library_root = self.root / "lib"
        self.library_root.mkdir()
        for i in range(30):
            author = self.library_root / f"Author {i}"
            author.mkdir()
            (author / f"Title {i}.mp3").write_bytes(b"x")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_target_indexes_raises_when_cancelled(self) -> None:
        with self.assertRaises(DiscoveryCancelled):
            build_target_indexes(
                self.library_root,
                should_cancel=lambda: True,
                cancel_check_interval=1,
            )

    def test_build_inode_index_raises_when_cancelled(self) -> None:
        from stager_core.staging import build_inode_index

        with self.assertRaises(DiscoveryCancelled):
            build_inode_index(
                self.library_root,
                should_cancel=lambda: True,
                cancel_check_interval=1,
            )

    def test_build_library_index_raises_when_cancelled(self) -> None:
        with self.assertRaises(DiscoveryCancelled):
            build_library_index(
                self.library_root,
                should_cancel=lambda: True,
                cancel_check_interval=1,
            )


class DiscoveryCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.books_root.mkdir()
        for i in range(20):
            (self.books_root / f"book{i}.mp3").write_bytes(b"x")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_discover_books_raises_when_cancelled_mid_build(self) -> None:
        cancel_after = 5
        seen = {"count": 0}

        def should_cancel() -> bool:
            return seen["count"] >= cancel_after

        def on_progress(count: int) -> None:
            seen["count"] = count

        with self.assertRaises(DiscoveryCancelled):
            discover_books(
                self.books_root,
                on_progress=on_progress,
                progress_interval=1,
                should_cancel=should_cancel,
            )
