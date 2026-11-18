from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.db import connect
from app.scan import ScanManager, ScanProgress
from stager_core.discovery import AudioFile, FlatBook


class ScanProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = connect(self.root / "test.db")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_counters_monotonic_and_aliases(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO scans (id, status, started_at, scan_phase)
                VALUES ('s1', 'running', 'now', 'discovering')
                """
            )
            self.conn.commit()

        progress = ScanProgress(self.conn, "s1", flush_interval_s=0)
        progress.set_discovered(3, "Discovering books… 3 found")
        progress.inc("books_tagged")
        progress.inc("books_indexed")
        progress.inc("books_metadata")
        progress.inc("books_complete")
        progress.flush(force=True)

        row = self.conn.execute("SELECT * FROM scans WHERE id = 's1'").fetchone()
        self.assertEqual(row["books_discovered"], 3)
        self.assertEqual(row["books_found"], 3)
        self.assertEqual(row["books_tagged"], 1)
        self.assertEqual(row["books_indexed"], 1)
        self.assertEqual(row["books_metadata"], 1)
        self.assertEqual(row["books_complete"], 1)
        self.assertEqual(row["metadata_done"], 1)

    def test_skip_lookup_does_not_increment_metadata(self) -> None:
        books_root = self.root / "src"
        library_root = self.root / "lib"
        books_root.mkdir()
        library_root.mkdir()
        book_dir = books_root / "Author" / "Title"
        book_dir.mkdir(parents=True)
        audio = book_dir / "book.m4b"
        audio.write_bytes(b"x" * 64)

        lib_dir = library_root / "Author" / "Title"
        lib_dir.mkdir(parents=True)
        lib_audio = lib_dir / "book.m4b"
        os.link(audio, lib_audio)

        book = FlatBook(
            id="book1",
            flatten_name="Title",
            source_path="Author/Title",
            source_path_parts=["Author", "Title"],
            top_level_pack="",
            parent_context="",
            grouping="folder",
            flatten_target="Author/Title",
            files=[AudioFile(name="book.m4b", source="Author/Title/book.m4b", size_bytes=64)],
        )

        manager = ScanManager(self.conn, books_root, library_root)
        inode_index = {audio.stat().st_ino: [str(lib_audio)]}

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO books (
                    id, scan_id, source_path, source_path_parts, top_level_pack,
                    parent_context, grouping, flatten_name, flatten_target, files_json,
                    status, suggested_author, suggested_title, confidence, staged_path,
                    tags_json, candidates_json, lookup_status, updated_at
                ) VALUES (
                    'book1', 'old', 'Author/Title', '["Author","Title"]', '',
                    '', 'folder', 'Title', 'Author/Title', '[]',
                    'staged', 'Author Name', 'Title', 0.95, 'Author/Title',
                    '{}', '[]', 'ok', 'now'
                )
                """
            )
            self.conn.commit()

        progress = ScanProgress(self.conn, "scan1", flush_interval_s=0)
        with patch.object(manager.lookup, "resolve_book") as resolve_mock:
            manager._upsert_book(
                "scan1",
                book,
                inode_index,
                progress=progress,
            )
            resolve_mock.assert_not_called()

        progress.flush(force=True)
        self.assertEqual(progress._counters["books_metadata"], 0)
        self.assertEqual(progress._counters["books_complete"], 1)
        self.assertEqual(progress._counters["books_indexed"], 1)
        self.assertEqual(progress._counters["books_tagged"], 1)

    @patch.dict(
        os.environ,
        {
            "GOOGLE_BOOKS_API_KEY": "",
            "STAGER_MAM_ID": "",
            "STAGER_MAM_COOKIE_FILE": r"Z:\__no_stager_mam_cookies__",
        },
        clear=False,
    )
    def test_scan_sets_phase_and_complete_counters(self) -> None:
        books_root = self.root / "src"
        library_root = self.root / "lib"
        books_root.mkdir()
        library_root.mkdir()
        book_dir = books_root / "Author" / "Title"
        book_dir.mkdir(parents=True)
        (book_dir / "book.m4b").write_bytes(b"x" * 64)

        book = FlatBook(
            id="book1",
            flatten_name="Title",
            source_path="Author/Title",
            source_path_parts=["Author", "Title"],
            top_level_pack="",
            parent_context="",
            grouping="folder",
            flatten_target="Author/Title",
            files=[AudioFile(name="book.m4b", source="Author/Title/book.m4b", size_bytes=64)],
        )

        manager = ScanManager(self.conn, books_root, library_root)

        def fake_discover(*_args, **kwargs):
            on_progress = kwargs.get("on_progress")
            if on_progress:
                on_progress(1)
            return [book]

        resolution = MagicMock()
        resolution.suggested_author = "Author Name"
        resolution.suggested_title = "Title"
        resolution.suggested_series = ""
        resolution.suggested_series_index = ""
        resolution.suggested_series_state = ""
        resolution.suggested_series_source = ""
        resolution.confidence = 0.9
        resolution.lookup_status = "ok"
        resolution.candidates = []
        resolution.tags = MagicMock(to_dict=lambda: {})
        resolution.lvi_match = {}
        resolution.book_breakdown = {}
        resolution.series_breakdown = {}
        resolution.confidence_breakdown = {}
        resolution.search_context = {}

        with patch("app.scan.discover_books", side_effect=fake_discover), patch(
            "stager_core.target_index.build_target_indexes", return_value=({}, {})
        ), patch.object(manager.lookup, "resolve_book", return_value=resolution):
            scan_id = manager.start_scan()
            deadline = time.time() + 5
            row = None
            while time.time() < deadline:
                row = self.conn.execute(
                    "SELECT * FROM scans WHERE id = ?", (scan_id,)
                ).fetchone()
                if row and row["status"] == "completed":
                    break
                time.sleep(0.05)

        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["total_books"], 1)
        self.assertEqual(row["books_discovered"], 1)
        self.assertEqual(row["books_complete"], 1)
        self.assertEqual(row["books_metadata"], 1)
        self.assertGreaterEqual(row["books_tagged"], 1)
        self.assertGreaterEqual(row["books_indexed"], 1)
