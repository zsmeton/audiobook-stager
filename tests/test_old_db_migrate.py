from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import connect

_OLD_SCHEMA = """
CREATE TABLE scans (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_books INTEGER DEFAULT 0,
    metadata_done INTEGER DEFAULT 0,
    message TEXT DEFAULT ''
);

CREATE TABLE books (
    id TEXT PRIMARY KEY,
    scan_id TEXT,
    source_path TEXT NOT NULL,
    source_path_parts TEXT NOT NULL,
    top_level_pack TEXT,
    parent_context TEXT,
    grouping TEXT,
    flatten_name TEXT,
    flatten_target TEXT,
    files_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    suggested_author TEXT DEFAULT '',
    suggested_title TEXT DEFAULT '',
    chosen_author TEXT DEFAULT '',
    chosen_title TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    staged_path TEXT DEFAULT '',
    tags_json TEXT DEFAULT '{}',
    candidates_json TEXT DEFAULT '[]',
    lookup_status TEXT DEFAULT '',
    error TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE auto_actions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    action TEXT NOT NULL,
    author TEXT DEFAULT '',
    title TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    staged_path TEXT DEFAULT '',
    source_path TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    dismissed_at TEXT
);

CREATE TABLE auto_settings (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    interval_hours REAL NOT NULL DEFAULT 2,
    min_confidence REAL NOT NULL DEFAULT 0.9,
    lock_timeout_minutes INTEGER NOT NULL DEFAULT 15,
    cache_relookup_pending INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

_BOOK_COLUMNS = {
    "merged_into",
    "chosen_series",
    "chosen_series_index",
    "suggested_series",
    "suggested_series_index",
    "suggested_series_state",
    "suggested_series_source",
    "chosen_author_set",
    "chosen_title_set",
    "chosen_series_set",
    "chosen_series_index_set",
    "lvi_match_json",
}

_SCAN_COLUMNS = {
    "books_found",
    "books_discovered",
    "books_tagged",
    "books_indexed",
    "books_metadata",
    "books_complete",
    "library_files_indexed",
    "scan_phase",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_old_book(
    raw: sqlite3.Connection,
    book_id: str,
    *,
    chosen_author: str,
    suggested_author: str,
    chosen_title: str,
    suggested_title: str,
) -> None:
    raw.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title, updated_at
        ) VALUES (?, 'seed/book', '["seed","book"]', '[]', 'pending', ?, ?, ?, ?, '2020-01-01')
        """,
        (book_id, suggested_author, suggested_title, chosen_author, chosen_title),
    )


class OldDatabaseMigrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "old.db"
        raw = sqlite3.connect(self.db_path)
        raw.executescript(_OLD_SCHEMA)
        raw.execute(
            """
            INSERT INTO scans (id, status, started_at, metadata_done)
            VALUES ('oldscan', 'completed', '2020-01-01', 3)
            """
        )
        _insert_old_book(
            raw,
            "match",
            chosen_author="Jane",
            suggested_author="Jane",
            chosen_title="Book",
            suggested_title="Book",
        )
        _insert_old_book(
            raw,
            "diverge",
            chosen_author="Manual Author",
            suggested_author="Jane",
            chosen_title="Other Title",
            suggested_title="Book",
        )
        raw.commit()
        raw.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_connect_adds_missing_columns_and_repairs_false_pins_once(self) -> None:
        conn = connect(self.db_path)
        self.assertTrue(_BOOK_COLUMNS <= _columns(conn, "books"))
        self.assertTrue(_SCAN_COLUMNS <= _columns(conn, "scans"))
        self.assertTrue({"review_outcome", "min_confidence"} <= _columns(conn, "auto_actions"))
        self.assertTrue(
            {
                "scan_manual_hints",
                "lvi_search",
                "lvi_boost",
                "title_extraction_mode",
                "title_cleanup_pre_json",
                "title_cleanup_post_json",
            }
            <= _columns(conn, "auto_settings")
        )
        self.assertIn(
            "file_fingerprints",
            {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            },
        )

        scan = conn.execute(
            """
            SELECT books_found, books_discovered, books_complete, metadata_done
            FROM scans WHERE id = 'oldscan'
            """
        ).fetchone()
        self.assertEqual(scan["metadata_done"], 3)
        self.assertEqual(scan["books_found"], 0)
        self.assertEqual(scan["books_discovered"], 0)
        self.assertEqual(scan["books_complete"], 3)

        settings = conn.execute(
            "SELECT * FROM auto_settings WHERE id = 'default'"
        ).fetchone()
        self.assertEqual(settings["scan_manual_hints"], 0)
        self.assertEqual(settings["lvi_search"], 1)
        self.assertEqual(settings["lvi_boost"], 1)
        self.assertEqual(settings["title_extraction_mode"], "balanced")
        self.assertEqual(settings["title_cleanup_pre_json"], "[]")
        self.assertEqual(settings["title_cleanup_post_json"], "[]")

        match = conn.execute(
            """
            SELECT chosen_author_set, chosen_title_set,
                   chosen_series_set, chosen_series_index_set
            FROM books WHERE id = 'match'
            """
        ).fetchone()
        self.assertEqual(int(match["chosen_author_set"]), 0)
        self.assertEqual(int(match["chosen_title_set"]), 0)
        self.assertEqual(int(match["chosen_series_set"]), 0)
        self.assertEqual(int(match["chosen_series_index_set"]), 0)

        diverge = conn.execute(
            """
            SELECT chosen_author, chosen_title, chosen_author_set, chosen_title_set
            FROM books WHERE id = 'diverge'
            """
        ).fetchone()
        self.assertEqual(diverge["chosen_author"], "Manual Author")
        self.assertEqual(diverge["chosen_title"], "Other Title")
        self.assertEqual(int(diverge["chosen_author_set"]), 1)
        self.assertEqual(int(diverge["chosen_title_set"]), 1)

        flag = conn.execute(
            "SELECT key FROM schema_flags WHERE key = 'repair_false_chosen_pins_v1'"
        ).fetchone()
        self.assertIsNotNone(flag)

        conn.execute(
            "UPDATE books SET chosen_author_set = 1 WHERE id = 'match'"
        )
        conn.commit()
        conn.close()

        again = connect(self.db_path)
        kept = again.execute(
            "SELECT chosen_author_set FROM books WHERE id = 'match'"
        ).fetchone()
        self.assertEqual(int(kept["chosen_author_set"]), 1)
        flags = again.execute(
            "SELECT COUNT(*) AS c FROM schema_flags WHERE key = 'repair_false_chosen_pins_v1'"
        ).fetchone()
        self.assertEqual(flags["c"], 1)
        again.close()
