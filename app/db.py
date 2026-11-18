from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.effective import (
    any_chosen_set,
    chosen_series_state,
    effective_metadata,
    target_key_preview,
)
from stager_core.metadata.normalize import provider_text
from stager_core.metadata.query import build_search_context
from stager_core.metadata.title_extraction import ADVANCED_DEFAULT_POST, ADVANCED_DEFAULT_PRE
from stager_core.metadata.types import TagInfo

DB_LOCK = threading.RLock()

_CANDIDATE_TEXT_FIELDS = ("author", "title", "series", "series_index", "narrator", "subtitle")


def _decode_candidates_payload(candidates: list[Any]) -> list[Any]:
    """Decode HTML entities in stored provider candidate strings for API/UI."""
    out: list[Any] = []
    for item in candidates:
        if not isinstance(item, dict):
            out.append(item)
            continue
        row = dict(item)
        for key in _CANDIDATE_TEXT_FIELDS:
            val = row.get(key)
            if isinstance(val, str) and val:
                row[key] = provider_text(val)
        out.append(row)
    return out


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_books INTEGER DEFAULT 0,
    metadata_done INTEGER DEFAULT 0,
    books_found INTEGER DEFAULT 0,
    books_discovered INTEGER DEFAULT 0,
    books_tagged INTEGER DEFAULT 0,
    books_indexed INTEGER DEFAULT 0,
    books_metadata INTEGER DEFAULT 0,
    books_complete INTEGER DEFAULT 0,
    library_files_indexed INTEGER DEFAULT 0,
    scan_phase TEXT DEFAULT '',
    message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS books (
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
    chosen_series TEXT DEFAULT '',
    chosen_series_index TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    staged_path TEXT DEFAULT '',
    tags_json TEXT DEFAULT '{}',
    candidates_json TEXT DEFAULT '[]',
    lookup_status TEXT DEFAULT '',
    error TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (scan_id) REFERENCES scans(id)
);

CREATE TABLE IF NOT EXISTS api_cache (
    provider TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    response_json TEXT NOT NULL,
    http_status INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (provider, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
CREATE INDEX IF NOT EXISTS idx_books_scan ON books(scan_id);
CREATE INDEX IF NOT EXISTS idx_books_source_path ON books(source_path);

CREATE TABLE IF NOT EXISTS conflict_resolutions (
    target_key TEXT PRIMARY KEY,
    winner_side TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS book_merges (
    primary_book_id TEXT NOT NULL,
    member_book_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_book_merges_primary ON book_merges(primary_book_id);

CREATE TABLE IF NOT EXISTS auto_settings (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    interval_hours REAL NOT NULL DEFAULT 2,
    min_confidence REAL NOT NULL DEFAULT 0.9,
    lock_timeout_minutes INTEGER NOT NULL DEFAULT 15,
    cache_relookup_pending INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auto_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    scan_id TEXT,
    books_eligible INTEGER DEFAULT 0,
    books_staged INTEGER DEFAULT 0,
    books_failed INTEGER DEFAULT 0,
    phase TEXT DEFAULT 'starting',
    message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS auto_actions (
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
    dismissed_at TEXT,
    review_outcome TEXT,
    min_confidence REAL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES auto_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_auto_actions_review
    ON auto_actions(dismissed_at, created_at);

CREATE TABLE IF NOT EXISTS auto_change_feedback (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    staged_author TEXT NOT NULL,
    staged_title TEXT NOT NULL,
    staged_path TEXT DEFAULT '',
    confidence REAL NOT NULL,
    min_confidence REAL NOT NULL,
    winning_source TEXT DEFAULT '',
    source_path TEXT NOT NULL,
    source_path_parts TEXT NOT NULL,
    parent_context TEXT DEFAULT '',
    flatten_name TEXT DEFAULT '',
    grouping TEXT DEFAULT '',
    top_level_pack TEXT DEFAULT '',
    files_json TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '{}',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    search_context_json TEXT NOT NULL DEFAULT '{}',
    lookup_status TEXT DEFAULT '',
    suggested_author TEXT DEFAULT '',
    suggested_title TEXT DEFAULT '',
    FOREIGN KEY (action_id) REFERENCES auto_actions(id)
);

CREATE INDEX IF NOT EXISTS idx_auto_feedback_decision
    ON auto_change_feedback(decision, decided_at);
CREATE INDEX IF NOT EXISTS idx_auto_feedback_source
    ON auto_change_feedback(winning_source);
CREATE INDEX IF NOT EXISTS idx_auto_feedback_confidence
    ON auto_change_feedback(confidence);

CREATE TABLE IF NOT EXISTS activity_lock (
    id TEXT PRIMARY KEY,
    locked_until TEXT NOT NULL,
    last_renewed_at TEXT NOT NULL,
    last_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS library_targets (
    target_key TEXT PRIMARY KEY,
    author_dir TEXT NOT NULL,
    title_dir TEXT NOT NULL,
    files_json TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_meta (
    id TEXT PRIMARY KEY,
    last_scan_id TEXT,
    last_scan_finished_at TEXT,
    last_source_discovery_at TEXT,
    source_book_count INTEGER DEFAULT 0,
    library_target_count INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Append-only resolver decision log. One row per resolve (scan/auto/manual),
-- capturing the full score_breakdown so priors/thresholds can be tuned against
-- real operator outcomes. Never UPDATE/DELETE in normal flow (no TTL).
CREATE TABLE IF NOT EXISTS lookup_decisions (
    id TEXT PRIMARY KEY,
    book_id TEXT,
    scan_id TEXT,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    winning_source TEXT,
    winning_author TEXT,
    winning_title TEXT,
    confidence REAL,
    raw_confidence REAL,
    status TEXT,
    cluster_size INTEGER,
    caps_applied TEXT,
    runner_up_confidence REAL,
    runner_up_source TEXT,
    families_json TEXT,
    evidence_json TEXT,
    search_context_json TEXT,
    tags_json TEXT,
    auto_run_id TEXT,
    auto_action_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_lookup_decisions_book
    ON lookup_decisions(book_id, created_at);
CREATE INDEX IF NOT EXISTS idx_lookup_decisions_source
    ON lookup_decisions(winning_source);
CREATE INDEX IF NOT EXISTS idx_lookup_decisions_status
    ON lookup_decisions(status);
CREATE INDEX IF NOT EXISTS idx_lookup_decisions_confidence
    ON lookup_decisions(confidence);

-- Append-only operator outcome log. One row per operator action, joinable to
-- lookup_decisions on book_id (latest decision at/just before the action).
CREATE TABLE IF NOT EXISTS decision_outcomes (
    id TEXT PRIMARY KEY,
    book_id TEXT,
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,
    author TEXT,
    title TEXT,
    prev_author TEXT DEFAULT '',
    prev_title TEXT DEFAULT '',
    confidence_at_action REAL DEFAULT 0,
    winning_source_at_action TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_decision_outcomes_book
    ON decision_outcomes(book_id, created_at);
CREATE INDEX IF NOT EXISTS idx_decision_outcomes_action
    ON decision_outcomes(action);

CREATE TABLE IF NOT EXISTS file_fingerprints (
    rel_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    algo_version INTEGER NOT NULL DEFAULT 1,
    fingerprint TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (rel_path, algo_version)
);

CREATE INDEX IF NOT EXISTS idx_file_fp_lookup
    ON file_fingerprints(rel_path, size_bytes, mtime_ns, algo_version);
"""


def _migrate_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(auto_actions)").fetchall()}
    if "review_outcome" not in columns:
        conn.execute("ALTER TABLE auto_actions ADD COLUMN review_outcome TEXT")
    if "min_confidence" not in columns:
        conn.execute("ALTER TABLE auto_actions ADD COLUMN min_confidence REAL DEFAULT 0")
    scan_columns = {row[1] for row in conn.execute("PRAGMA table_info(scans)").fetchall()}
    if "books_found" not in scan_columns:
        conn.execute("ALTER TABLE scans ADD COLUMN books_found INTEGER DEFAULT 0")
    scan_progress_columns = (
        ("books_discovered", "INTEGER DEFAULT 0"),
        ("books_tagged", "INTEGER DEFAULT 0"),
        ("books_indexed", "INTEGER DEFAULT 0"),
        ("books_metadata", "INTEGER DEFAULT 0"),
        ("books_complete", "INTEGER DEFAULT 0"),
        ("library_files_indexed", "INTEGER DEFAULT 0"),
        ("scan_phase", "TEXT DEFAULT ''"),
    )
    for col, typedef in scan_progress_columns:
        if col not in scan_columns:
            conn.execute(f"ALTER TABLE scans ADD COLUMN {col} {typedef}")
            scan_columns.add(col)
    conn.execute(
        """
        UPDATE scans
        SET books_discovered = books_found
        WHERE COALESCE(books_discovered, 0) = 0 AND COALESCE(books_found, 0) > 0
        """
    )
    conn.execute(
        """
        UPDATE scans
        SET books_complete = metadata_done
        WHERE COALESCE(books_complete, 0) = 0 AND COALESCE(metadata_done, 0) > 0
        """
    )
    book_columns = {row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
    if "merged_into" not in book_columns:
        conn.execute("ALTER TABLE books ADD COLUMN merged_into TEXT DEFAULT ''")
    if "chosen_series" not in book_columns:
        conn.execute("ALTER TABLE books ADD COLUMN chosen_series TEXT DEFAULT ''")
    if "chosen_series_index" not in book_columns:
        conn.execute("ALTER TABLE books ADD COLUMN chosen_series_index TEXT DEFAULT ''")
    series_suggested = (
        ("suggested_series", "TEXT DEFAULT ''"),
        ("suggested_series_index", "TEXT DEFAULT ''"),
        ("suggested_series_state", "TEXT DEFAULT ''"),
        ("suggested_series_source", "TEXT DEFAULT ''"),
        ("chosen_author_set", "INTEGER DEFAULT 0"),
        ("chosen_title_set", "INTEGER DEFAULT 0"),
        ("chosen_series_set", "INTEGER DEFAULT 0"),
        ("chosen_series_index_set", "INTEGER DEFAULT 0"),
    )
    added_pin_columns = False
    for col, typedef in series_suggested:
        if col not in book_columns:
            conn.execute(f"ALTER TABLE books ADD COLUMN {col} {typedef}")
            book_columns.add(col)
            if col.endswith("_set"):
                added_pin_columns = True
    # One-time backfill for DBs that predate pin flags: non-empty chosen_* used
    # to mean "operator override". Must not re-run — staging snapshots also
    # write chosen_* without setting the flags.
    if added_pin_columns:
        conn.execute(
            """
            UPDATE books SET chosen_author_set = 1
            WHERE chosen_author != '' AND COALESCE(chosen_author_set, 0) = 0
            """
        )
        conn.execute(
            """
            UPDATE books SET chosen_title_set = 1
            WHERE chosen_title != '' AND COALESCE(chosen_title_set, 0) = 0
            """
        )
        conn.execute(
            """
            UPDATE books SET chosen_series_set = 1
            WHERE chosen_series != '' AND COALESCE(chosen_series_set, 0) = 0
            """
        )
        conn.execute(
            """
            UPDATE books SET chosen_series_index_set = 1
            WHERE chosen_series_index != '' AND COALESCE(chosen_series_index_set, 0) = 0
            """
        )
    _repair_false_chosen_pins(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_books_source_path ON books(source_path)"
    )
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "file_fingerprints" not in tables:
        conn.executescript(
            """
            CREATE TABLE file_fingerprints (
                rel_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                algo_version INTEGER NOT NULL DEFAULT 1,
                fingerprint TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (rel_path, algo_version)
            );
            CREATE INDEX idx_file_fp_lookup
                ON file_fingerprints(rel_path, size_bytes, mtime_ns, algo_version);
            """
        )
    auto_columns = {row[1] for row in conn.execute("PRAGMA table_info(auto_settings)").fetchall()}
    if "scan_manual_hints" not in auto_columns:
        conn.execute(
            "ALTER TABLE auto_settings ADD COLUMN scan_manual_hints INTEGER NOT NULL DEFAULT 0"
        )
    if "lvi_search" not in auto_columns:
        conn.execute(
            "ALTER TABLE auto_settings ADD COLUMN lvi_search INTEGER NOT NULL DEFAULT 1"
        )
    if "lvi_boost" not in auto_columns:
        conn.execute(
            "ALTER TABLE auto_settings ADD COLUMN lvi_boost INTEGER NOT NULL DEFAULT 1"
        )
    auto_columns = {row[1] for row in conn.execute("PRAGMA table_info(auto_settings)").fetchall()}
    if "title_extraction_mode" not in auto_columns:
        conn.execute(
            "ALTER TABLE auto_settings ADD COLUMN title_extraction_mode TEXT NOT NULL DEFAULT 'balanced'"
        )
    if "title_cleanup_pre_json" not in auto_columns:
        conn.execute(
            "ALTER TABLE auto_settings ADD COLUMN title_cleanup_pre_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "title_cleanup_post_json" not in auto_columns:
        conn.execute(
            "ALTER TABLE auto_settings ADD COLUMN title_cleanup_post_json TEXT NOT NULL DEFAULT '[]'"
        )
    book_columns = {row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
    if "lvi_match_json" not in book_columns:
        conn.execute(
            "ALTER TABLE books ADD COLUMN lvi_match_json TEXT NOT NULL DEFAULT '{}'"
        )


def _ensure_schema_flags(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_flags (
            key TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _schema_flag_applied(conn: sqlite3.Connection, key: str) -> bool:
    _ensure_schema_flags(conn)
    row = conn.execute("SELECT 1 FROM schema_flags WHERE key = ?", (key,)).fetchone()
    return row is not None


def _set_schema_flag(conn: sqlite3.Connection, key: str) -> None:
    _ensure_schema_flags(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_flags (key, applied_at) VALUES (?, ?)",
        (key, _utcnow()),
    )


def _repair_false_chosen_pins(conn: sqlite3.Connection) -> None:
    """Unpin staging snapshots that the unbounded chosen_*_set backfill marked manual.

    Approve/auto-stage copy effective metadata into chosen_* without pin flags.
    An older migrate treated any non-empty chosen_* as an operator pin on every
    connect, so scanned/staged books showed as Manual. Values that still differ
    from suggested_* are kept as real edits.
    """
    if _schema_flag_applied(conn, "repair_false_chosen_pins_v1"):
        return
    pairs = (
        ("chosen_author_set", "chosen_author", "suggested_author"),
        ("chosen_title_set", "chosen_title", "suggested_title"),
        ("chosen_series_set", "chosen_series", "suggested_series"),
        ("chosen_series_index_set", "chosen_series_index", "suggested_series_index"),
    )
    for flag, chosen, suggested in pairs:
        conn.execute(
            f"""
            UPDATE books SET {flag} = 0
            WHERE COALESCE({flag}, 0) = 1
              AND TRIM(COALESCE({chosen}, '')) = TRIM(COALESCE({suggested}, ''))
            """
        )
    _set_schema_flag(conn, "repair_false_chosen_pins_v1")


def connect(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    _migrate_schema(conn)
    ensure_auto_defaults(conn)
    ensure_session_meta_defaults(conn)
    conn.commit()
    return conn


@contextmanager
def db_conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_file)
    try:
        yield conn
    finally:
        conn.close()


def row_to_book(row: sqlite3.Row, *, in_conflict: bool = False, target_key: str = "") -> dict[str, Any]:
    files = json.loads(row["files_json"])
    row_dict = dict(row)
    eff = effective_metadata(row_dict)
    preview = target_key_preview(row_dict)
    staging_confidence = float(row["confidence"] or 0)
    return {
        "id": row["id"],
        "scan_id": row["scan_id"],
        "source_path": row["source_path"],
        "source_path_parts": json.loads(row["source_path_parts"]),
        "top_level_pack": row["top_level_pack"],
        "parent_context": row["parent_context"],
        "grouping": row["grouping"],
        "flatten_name": row["flatten_name"],
        "flatten_target": row["flatten_target"],
        "files": files,
        "file_count": len(files),
        "status": row["status"],
        "suggested_author": row["suggested_author"],
        "suggested_title": row["suggested_title"],
        "suggested_series": row_dict.get("suggested_series") or "",
        "suggested_series_index": row_dict.get("suggested_series_index") or "",
        "suggested_series_state": row_dict.get("suggested_series_state") or "",
        "suggested_series_source": row_dict.get("suggested_series_source") or "",
        "chosen_author": row["chosen_author"],
        "chosen_title": row["chosen_title"],
        "chosen_author_set": int(row_dict.get("chosen_author_set") or 0),
        "chosen_title_set": int(row_dict.get("chosen_title_set") or 0),
        "chosen_series": row_dict.get("chosen_series") or "",
        "chosen_series_index": row_dict.get("chosen_series_index") or "",
        "chosen_series_set": int(row_dict.get("chosen_series_set") or 0),
        "chosen_series_index_set": int(row_dict.get("chosen_series_index_set") or 0),
        "chosen_series_state": chosen_series_state(row_dict),
        **eff,
        "staging_confidence": staging_confidence,
        "confidence": staging_confidence,
        "target_key_preview": preview,
        "any_chosen_set": any_chosen_set(row_dict),
        "staged_path": row["staged_path"],
        "tags": json.loads(row["tags_json"] or "{}"),
        "candidates": _decode_candidates_payload(json.loads(row["candidates_json"] or "[]")),
        "lookup_status": row["lookup_status"],
        "error": row["error"],
        "updated_at": row["updated_at"],
        "merged_into": row["merged_into"] if "merged_into" in row.keys() else "",
        "target_key": target_key or preview,
        "in_conflict": in_conflict,
    }


def load_conflict_resolutions(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT target_key, winner_side FROM conflict_resolutions").fetchall()
    return {r["target_key"]: r["winner_side"] for r in rows}


def ensure_session_meta_defaults(conn: sqlite3.Connection) -> None:
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO session_meta (
            id, last_scan_id, last_scan_finished_at, last_source_discovery_at,
            source_book_count, library_target_count, updated_at
        ) VALUES ('default', NULL, NULL, NULL, 0, 0, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (now,),
    )


def get_session_meta(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_session_meta_defaults(conn)
    row = conn.execute("SELECT * FROM session_meta WHERE id = 'default'").fetchone()
    assert row is not None
    return dict(row)


def update_session_meta(conn: sqlite3.Connection, **fields: Any) -> dict[str, Any]:
    ensure_session_meta_defaults(conn)
    allowed = {
        "last_scan_id": "last_scan_id",
        "last_scan_finished_at": "last_scan_finished_at",
        "last_source_discovery_at": "last_source_discovery_at",
        "source_book_count": "source_book_count",
        "library_target_count": "library_target_count",
    }
    sets: list[str] = []
    values: list[Any] = []
    for key, column in allowed.items():
        if key not in fields or fields[key] is None:
            continue
        sets.append(f"{column} = ?")
        values.append(fields[key])
    if sets:
        sets.append("updated_at = ?")
        values.append(_utcnow())
        conn.execute(
            f"UPDATE session_meta SET {', '.join(sets)} WHERE id = 'default'",
            values,
        )
        conn.commit()
    return get_session_meta(conn)


def save_library_targets(conn: sqlite3.Connection, library_index: dict[str, Any]) -> None:
    now = _utcnow()
    conn.execute("DELETE FROM library_targets")
    for target_key, side in library_index.items():
        if "/" in target_key:
            author_dir, title_dir = target_key.split("/", 1)
        else:
            author_dir, title_dir = target_key, ""
        files = side.files if hasattr(side, "files") else side.get("files", [])
        tags = side.tags if hasattr(side, "tags") else side.get("tags")
        if hasattr(tags, "to_dict"):
            tags_json = json.dumps(tags.to_dict())
        elif isinstance(tags, dict):
            tags_json = json.dumps(tags)
        else:
            tags_json = "{}"
        conn.execute(
            """
            INSERT INTO library_targets (
                target_key, author_dir, title_dir, files_json, tags_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                target_key,
                author_dir,
                title_dir,
                json.dumps(files),
                tags_json,
                now,
            ),
        )
    conn.commit()


def upsert_library_target(conn: sqlite3.Connection, side: Any) -> None:
    target_key = side.target_key
    if "/" in target_key:
        author_dir, title_dir = target_key.split("/", 1)
    else:
        author_dir, title_dir = target_key, ""
    tags = side.tags
    tags_json = json.dumps(tags.to_dict()) if hasattr(tags, "to_dict") else json.dumps(tags or {})
    conn.execute(
        """
        INSERT INTO library_targets (
            target_key, author_dir, title_dir, files_json, tags_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_key) DO UPDATE SET
            author_dir = excluded.author_dir,
            title_dir = excluded.title_dir,
            files_json = excluded.files_json,
            tags_json = excluded.tags_json,
            updated_at = excluded.updated_at
        """,
        (
            target_key,
            author_dir,
            title_dir,
            json.dumps(side.files),
            tags_json,
            _utcnow(),
        ),
    )
    conn.commit()


def delete_library_target(conn: sqlite3.Connection, target_key: str) -> None:
    conn.execute("DELETE FROM library_targets WHERE target_key = ?", (target_key,))
    conn.commit()


def load_library_targets(conn: sqlite3.Connection) -> dict[str, Any]:
    from stager_core.conflicts import LibrarySide
    from stager_core.metadata.types import TagInfo

    rows = conn.execute("SELECT * FROM library_targets").fetchall()
    index: dict[str, LibrarySide] = {}
    for row in rows:
        tags_dict = json.loads(row["tags_json"] or "{}")
        tags = TagInfo(
            title=tags_dict.get("title", ""),
            album=tags_dict.get("album", ""),
            artist=tags_dict.get("artist", ""),
            albumartist=tags_dict.get("albumartist", ""),
            asin=tags_dict.get("asin", ""),
            narrator=tags_dict.get("narrator", ""),
        )
        index[row["target_key"]] = LibrarySide(
            target_key=row["target_key"],
            files=json.loads(row["files_json"]),
            tags=tags,
        )
    return index


def count_books(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM books").fetchone()
    return int(row["c"]) if row else 0


def ensure_auto_defaults(conn: sqlite3.Connection) -> None:
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO auto_settings (
            id, enabled, interval_hours, min_confidence, lock_timeout_minutes,
            cache_relookup_pending, updated_at
        ) VALUES ('default', 0, 2, 0.9, 15, 0, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO activity_lock (id, locked_until, last_renewed_at, last_reason)
        VALUES ('default', ?, ?, '')
        ON CONFLICT(id) DO NOTHING
        """,
        (now, now),
    )


def get_auto_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_auto_defaults(conn)
    row = conn.execute("SELECT * FROM auto_settings WHERE id = 'default'").fetchone()
    assert row is not None
    keys = row.keys()
    pre_json = row["title_cleanup_pre_json"] if "title_cleanup_pre_json" in keys else "[]"
    post_json = row["title_cleanup_post_json"] if "title_cleanup_post_json" in keys else "[]"
    try:
        title_cleanup_pre = json.loads(pre_json) if pre_json else []
    except json.JSONDecodeError:
        title_cleanup_pre = []
    try:
        title_cleanup_post = json.loads(post_json) if post_json else []
    except json.JSONDecodeError:
        title_cleanup_post = []
    if not isinstance(title_cleanup_pre, list):
        title_cleanup_pre = []
    if not isinstance(title_cleanup_post, list):
        title_cleanup_post = []
    mode = row["title_extraction_mode"] if "title_extraction_mode" in keys else "balanced"
    if mode not in ("conservative", "balanced", "advanced"):
        mode = "balanced"
    if mode == "advanced" and not title_cleanup_pre and not title_cleanup_post:
        title_cleanup_pre = sorted(ADVANCED_DEFAULT_PRE)
        title_cleanup_post = sorted(ADVANCED_DEFAULT_POST)
    return {
        "enabled": bool(row["enabled"]),
        "interval_hours": float(row["interval_hours"]),
        "min_confidence": float(row["min_confidence"]),
        "lock_timeout_minutes": int(row["lock_timeout_minutes"]),
        "cache_relookup_pending": bool(row["cache_relookup_pending"]),
        "scan_manual_hints": bool(row["scan_manual_hints"]),
        "lvi_search": bool(row["lvi_search"] if "lvi_search" in keys else 1),
        "lvi_boost": bool(row["lvi_boost"] if "lvi_boost" in keys else 1),
        "title_extraction_mode": mode,
        "title_cleanup_pre": title_cleanup_pre,
        "title_cleanup_post": title_cleanup_post,
        "updated_at": row["updated_at"],
    }


def update_auto_settings(conn: sqlite3.Connection, **fields: Any) -> dict[str, Any]:
    ensure_auto_defaults(conn)
    allowed = {
        "enabled": "enabled",
        "interval_hours": "interval_hours",
        "min_confidence": "min_confidence",
        "lock_timeout_minutes": "lock_timeout_minutes",
        "cache_relookup_pending": "cache_relookup_pending",
        "scan_manual_hints": "scan_manual_hints",
        "lvi_search": "lvi_search",
        "lvi_boost": "lvi_boost",
        "title_extraction_mode": "title_extraction_mode",
        "title_cleanup_pre_json": "title_cleanup_pre_json",
        "title_cleanup_post_json": "title_cleanup_post_json",
    }
    sets: list[str] = []
    values: list[Any] = []
    for key, column in allowed.items():
        if key not in fields or fields[key] is None:
            continue
        value = fields[key]
        if key in ("enabled", "cache_relookup_pending", "scan_manual_hints", "lvi_search", "lvi_boost"):
            value = 1 if value else 0
        sets.append(f"{column} = ?")
        values.append(value)
    if sets:
        sets.append("updated_at = ?")
        values.append(_utcnow())
        conn.execute(
            f"UPDATE auto_settings SET {', '.join(sets)} WHERE id = 'default'",
            values,
        )
        conn.commit()
    return get_auto_settings(conn)


def get_last_auto_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM auto_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def save_conflict_resolution(conn: sqlite3.Connection, target_key: str, winner_side: str) -> None:
    conn.execute(
        """
        INSERT INTO conflict_resolutions (target_key, winner_side, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(target_key) DO UPDATE SET
            winner_side = excluded.winner_side,
            updated_at = excluded.updated_at
        """,
        (target_key, winner_side, _utcnow()),
    )


def clear_conflict_resolution_for_key(conn: sqlite3.Connection, target_key: str) -> None:
    conn.execute("DELETE FROM conflict_resolutions WHERE target_key = ?", (target_key,))


def save_book_merge(
    conn: sqlite3.Connection,
    primary_book_id: str,
    member_book_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO book_merges (primary_book_id, member_book_id, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(member_book_id) DO UPDATE SET
            primary_book_id = excluded.primary_book_id,
            created_at = excluded.created_at
        """,
        (primary_book_id, member_book_id, _utcnow()),
    )


def load_merged_members(conn: sqlite3.Connection, primary_book_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT member_book_id FROM book_merges WHERE primary_book_id = ? ORDER BY created_at",
        (primary_book_id,),
    ).fetchall()
    return [r["member_book_id"] for r in rows]


def delete_book_merges(conn: sqlite3.Connection, primary_book_id: str) -> None:
    conn.execute("DELETE FROM book_merges WHERE primary_book_id = ?", (primary_book_id,))


_METADATA_MIGRATE_FIELDS = (
    "chosen_author",
    "chosen_title",
    "chosen_series",
    "chosen_series_index",
    "chosen_author_set",
    "chosen_title_set",
    "chosen_series_set",
    "chosen_series_index_set",
    "suggested_author",
    "suggested_title",
    "suggested_series",
    "suggested_series_index",
    "suggested_series_state",
    "suggested_series_source",
    "confidence",
    "tags_json",
    "candidates_json",
    "lookup_status",
)


def _metadata_field_empty(name: str, value: object) -> bool:
    if name.endswith("_set"):
        return not int(value or 0)
    if name == "confidence":
        return value is None or float(value) == 0.0
    if name in {"tags_json", "candidates_json"}:
        text = str(value or "").strip()
        return not text or text in {"{}", "[]"}
    return not str(value or "").strip()


def find_metadata_donor_row(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    staged_path: str,
    exclude_id: str,
) -> sqlite3.Row | None:
    columns = ", ".join(_METADATA_MIGRATE_FIELDS)
    if staged_path:
        row = conn.execute(
            f"""
            SELECT {columns}
            FROM books
            WHERE id != ? AND staged_path = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (exclude_id, staged_path),
        ).fetchone()
        if row is not None:
            return row
    rows = conn.execute(
        f"""
        SELECT {columns}
        FROM books
        WHERE id != ? AND source_path = ?
        ORDER BY updated_at DESC
        """,
        (exclude_id, source_path),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    return None


def migrate_orphan_book_metadata(
    conn: sqlite3.Connection,
    discovered_ids: set[str],
) -> int:
    """Copy metadata from superseded rows onto current discovery successors."""
    if not discovered_ids:
        return 0

    placeholders = ",".join("?" * len(discovered_ids))
    id_list = sorted(discovered_ids)
    with DB_LOCK:
        successors = conn.execute(
            f"SELECT * FROM books WHERE id IN ({placeholders})",
            id_list,
        ).fetchall()
        orphans = [
            row
            for row in conn.execute("SELECT * FROM books").fetchall()
            if row["id"] not in discovered_ids
        ]

    if not orphans:
        return 0

    successor_by_id = {row["id"]: dict(row) for row in successors}
    by_staged_path: dict[str, list[str]] = {}
    by_source_path: dict[str, list[str]] = {}
    for row in successors:
        staged_path = (row["staged_path"] or "").strip()
        if staged_path:
            by_staged_path.setdefault(staged_path, []).append(row["id"])
        by_source_path.setdefault(row["source_path"], []).append(row["id"])

    orphans.sort(key=lambda row: row["updated_at"] or "", reverse=True)
    updated = 0
    now = _utcnow()

    for orphan in orphans:
        successor_id = _pick_successor_id(orphan, by_staged_path, by_source_path)
        if not successor_id or successor_id not in successor_by_id:
            continue

        successor = successor_by_id[successor_id]
        sets: list[str] = []
        values: list[object] = []

        for field in _METADATA_MIGRATE_FIELDS:
            orphan_val = orphan[field]
            if _metadata_field_empty(field, successor.get(field)) and not _metadata_field_empty(
                field, orphan_val
            ):
                sets.append(f"{field} = ?")
                values.append(orphan_val)
                successor[field] = orphan_val

        if orphan["status"] == "skipped" and successor.get("status") == "pending":
            sets.append("status = ?")
            values.append("skipped")
            successor["status"] = "skipped"

        if not sets:
            continue

        sets.append("updated_at = ?")
        values.append(now)
        values.append(successor_id)
        with DB_LOCK:
            conn.execute(
                f"UPDATE books SET {', '.join(sets)} WHERE id = ?",
                values,
            )
        updated += 1

    if updated:
        with DB_LOCK:
            conn.commit()
    return updated


def _pick_successor_id(
    orphan: sqlite3.Row,
    by_staged_path: dict[str, list[str]],
    by_source_path: dict[str, list[str]],
) -> str | None:
    staged_path = (orphan["staged_path"] or "").strip()
    if staged_path:
        candidates = by_staged_path.get(staged_path, [])
        if len(candidates) == 1:
            return candidates[0]

    source_path = orphan["source_path"]
    candidates = by_source_path.get(source_path, [])
    if len(candidates) == 1:
        return candidates[0]
    return None


def delete_books_by_ids(conn: sqlite3.Connection, book_ids: list[str]) -> None:
    if not book_ids:
        return

    batch_size = 500
    now = _utcnow()
    for i in range(0, len(book_ids), batch_size):
        batch = book_ids[i : i + batch_size]
        placeholders = ",".join("?" * len(batch))
        with DB_LOCK:
            conn.execute(
                f"""
                UPDATE auto_actions SET dismissed_at = ?
                WHERE dismissed_at IS NULL AND book_id IN ({placeholders})
                """,
                [now, *batch],
            )
            conn.execute(
                f"DELETE FROM book_merges WHERE member_book_id IN ({placeholders})",
                batch,
            )
            conn.execute(
                f"DELETE FROM book_merges WHERE primary_book_id IN ({placeholders})",
                batch,
            )
            conn.execute(
                f"DELETE FROM books WHERE id IN ({placeholders})",
                batch,
            )
            conn.commit()


def _derive_winning_source(
    candidates: list[dict[str, Any]],
    suggested_author: str,
    suggested_title: str,
) -> str:
    author_key = suggested_author.strip().lower()
    title_key = suggested_title.strip().lower()
    for cand in candidates:
        cand_author = (cand.get("author") or "").strip().lower()
        cand_title = (cand.get("title") or "").strip().lower()
        if not cand_title:
            continue
        if author_key and title_key:
            if cand_author == author_key and cand_title == title_key:
                return cand.get("source") or ""
        elif cand_title == title_key:
            return cand.get("source") or ""
    for cand in candidates:
        if (cand.get("title") or "").strip():
            return cand.get("source") or ""
    return ""


def _flatbook_from_feedback_row(row: sqlite3.Row) -> FlatBook:
    files = [
        AudioFile(name=f["name"], source=f["source"], size_bytes=f["size_bytes"])
        for f in json.loads(row["files_json"])
    ]
    return FlatBook(
        id=row["book_id"],
        flatten_name=row["flatten_name"] or "",
        source_path=row["source_path"] or "",
        source_path_parts=json.loads(row["source_path_parts"]),
        top_level_pack=row["top_level_pack"],
        parent_context=row["parent_context"],
        grouping=row["grouping"],
        files=files,
        flatten_target=row["flatten_target"] or "",
    )


def _tags_from_json(tags_json: str) -> TagInfo:
    tags_dict = json.loads(tags_json or "{}")
    return TagInfo(
        title=tags_dict.get("title", ""),
        album=tags_dict.get("album", ""),
        artist=tags_dict.get("artist", ""),
        albumartist=tags_dict.get("albumartist", ""),
        asin=tags_dict.get("asin", ""),
        narrator=tags_dict.get("narrator", ""),
        raw=tags_dict.get("raw", {}),
    )


def dismiss_auto_actions_for_book(conn: sqlite3.Connection, book_id: str) -> None:
    """Clear review-queue rows after operator manually staged the book."""
    now = _utcnow()
    with DB_LOCK:
        conn.execute(
            """
            UPDATE auto_actions SET dismissed_at = ?
            WHERE book_id = ? AND dismissed_at IS NULL
            """,
            (now, book_id),
        )
        conn.commit()


def record_auto_change_feedback(
    conn: sqlite3.Connection,
    *,
    action_id: str,
    decision: str,
) -> str | None:
    if decision not in {"approved", "rejected"}:
        return None

    existing = conn.execute(
        "SELECT id FROM auto_change_feedback WHERE action_id = ?",
        (action_id,),
    ).fetchone()
    if existing:
        return existing["id"]

    row = conn.execute(
        """
        SELECT
            a.id AS action_id, a.run_id, a.book_id, a.author, a.title, a.confidence,
            a.staged_path, a.source_path AS action_source_path, a.min_confidence,
            b.source_path, b.source_path_parts, b.top_level_pack, b.parent_context,
            b.grouping, b.flatten_name, b.flatten_target, b.files_json, b.tags_json,
            b.candidates_json, b.lookup_status, b.suggested_author, b.suggested_title
        FROM auto_actions a
        JOIN books b ON b.id = a.book_id
        WHERE a.id = ?
        """,
        (action_id,),
    ).fetchone()
    if not row:
        return None

    tags = _tags_from_json(row["tags_json"])
    candidates = json.loads(row["candidates_json"] or "[]")
    book = _flatbook_from_feedback_row(row)
    search_context = build_search_context(book, tags)
    winning_source = _derive_winning_source(
        candidates,
        row["suggested_author"] or "",
        row["suggested_title"] or "",
    )

    feedback_id = uuid.uuid4().hex[:12]
    now = _utcnow()
    source_path = row["action_source_path"] or row["source_path"] or book.source_path
    min_confidence = float(row["min_confidence"] or 0)

    conn.execute(
        """
        INSERT INTO auto_change_feedback (
            id, action_id, run_id, book_id, decision, decided_at,
            staged_author, staged_title, staged_path, confidence, min_confidence,
            winning_source, source_path, source_path_parts, parent_context, flatten_name,
            grouping, top_level_pack, files_json, tags_json, candidates_json,
            search_context_json, lookup_status, suggested_author, suggested_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            feedback_id,
            action_id,
            row["run_id"],
            row["book_id"],
            decision,
            now,
            row["author"] or "",
            row["title"] or "",
            row["staged_path"] or "",
            float(row["confidence"] or 0),
            min_confidence,
            winning_source,
            source_path,
            row["source_path_parts"],
            row["parent_context"] or "",
            row["flatten_name"] or "",
            row["grouping"] or "",
            row["top_level_pack"] or "",
            row["files_json"],
            row["tags_json"] or "{}",
            row["candidates_json"] or "[]",
            json.dumps(search_context),
            row["lookup_status"] or "",
            row["suggested_author"] or "",
            row["suggested_title"] or "",
        ),
    )
    conn.execute(
        "UPDATE auto_actions SET review_outcome = ? WHERE id = ?",
        (decision, action_id),
    )
    return feedback_id


# ---------------------------------------------------------- decision logging (P1.5)
def _winning_source_from_candidates(
    candidates: list[dict[str, Any]],
    suggested_author: str = "",
    suggested_title: str = "",
) -> str:
    """Prefer the scored winner's representative source; else best-effort match."""
    for cand in candidates:
        breakdown = cand.get("score_breakdown") or {}
        rep = breakdown.get("representative") or {}
        if rep.get("source"):
            return rep["source"]
    return _derive_winning_source(candidates, suggested_author, suggested_title)


def _decision_fields_from_breakdown(breakdown: dict[str, Any]) -> dict[str, Any]:
    """Flatten a scoring.score_breakdown into lookup_decisions columns."""
    breakdown = breakdown or {}
    rep = breakdown.get("representative") or {}
    runner_up = breakdown.get("runner_up") or {}
    return {
        "winning_source": rep.get("source", ""),
        "winning_author": rep.get("author", ""),
        "winning_title": rep.get("title", ""),
        "confidence": breakdown.get("confidence"),
        "raw_confidence": breakdown.get("raw_confidence"),
        "status": breakdown.get("status", ""),
        "cluster_size": breakdown.get("cluster_size", 0),
        "caps_applied": json.dumps(breakdown.get("caps_applied") or []),
        "runner_up_confidence": (runner_up.get("confidence") if runner_up else None),
        "runner_up_source": (runner_up.get("source", "") if runner_up else ""),
        "families_json": json.dumps(breakdown.get("families") or {}),
        "evidence_json": json.dumps(breakdown.get("evidence_pool") or []),
    }


def insert_lookup_decision(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    trigger: str,
    breakdown: dict[str, Any],
    scan_id: str | None = None,
    search_context: dict[str, Any] | None = None,
    tags: dict[str, Any] | None = None,
    auto_run_id: str | None = None,
    auto_action_id: str | None = None,
) -> str:
    """Append one resolver decision row built from a scoring breakdown."""
    fields = _decision_fields_from_breakdown(breakdown)
    decision_id = uuid.uuid4().hex[:12]
    with DB_LOCK:
        conn.execute(
            """
            INSERT INTO lookup_decisions (
                id, book_id, scan_id, created_at, trigger,
                winning_source, winning_author, winning_title,
                confidence, raw_confidence, status, cluster_size, caps_applied,
                runner_up_confidence, runner_up_source,
                families_json, evidence_json, search_context_json, tags_json,
                auto_run_id, auto_action_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                book_id,
                scan_id,
                _utcnow(),
                trigger,
                fields["winning_source"],
                fields["winning_author"],
                fields["winning_title"],
                fields["confidence"],
                fields["raw_confidence"],
                fields["status"],
                fields["cluster_size"],
                fields["caps_applied"],
                fields["runner_up_confidence"],
                fields["runner_up_source"],
                fields["families_json"],
                fields["evidence_json"],
                json.dumps(search_context or {}),
                json.dumps(tags or {}),
                auto_run_id,
                auto_action_id,
            ),
        )
        conn.commit()
    return decision_id


def insert_decision_outcome(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    action: str,
    author: str = "",
    title: str = "",
    prev_author: str = "",
    prev_title: str = "",
    confidence_at_action: float | None = None,
    winning_source_at_action: str | None = None,
) -> str:
    """Append one operator-outcome row, joinable to lookup_decisions by book_id.

    When ``confidence_at_action``/``winning_source_at_action`` are omitted they
    are read from the book's current row (confidence column + candidates_json).
    """
    if confidence_at_action is None or winning_source_at_action is None:
        row = conn.execute(
            "SELECT confidence, candidates_json, suggested_author, suggested_title "
            "FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if row is not None:
            if confidence_at_action is None:
                confidence_at_action = float(row["confidence"] or 0)
            if winning_source_at_action is None:
                winning_source_at_action = _winning_source_from_candidates(
                    json.loads(row["candidates_json"] or "[]"),
                    row["suggested_author"] or "",
                    row["suggested_title"] or "",
                )
    outcome_id = uuid.uuid4().hex[:12]
    with DB_LOCK:
        conn.execute(
            """
            INSERT INTO decision_outcomes (
                id, book_id, created_at, action, author, title,
                prev_author, prev_title, confidence_at_action, winning_source_at_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome_id,
                book_id,
                _utcnow(),
                action,
                author or "",
                title or "",
                prev_author or "",
                prev_title or "",
                float(confidence_at_action or 0),
                winning_source_at_action or "",
            ),
        )
        conn.commit()
    return outcome_id


def row_to_lookup_decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "book_id": row["book_id"],
        "scan_id": row["scan_id"],
        "created_at": row["created_at"],
        "trigger": row["trigger"],
        "winning_source": row["winning_source"],
        "winning_author": row["winning_author"],
        "winning_title": row["winning_title"],
        "confidence": row["confidence"],
        "raw_confidence": row["raw_confidence"],
        "status": row["status"],
        "cluster_size": row["cluster_size"],
        "caps_applied": json.loads(row["caps_applied"] or "[]"),
        "runner_up_confidence": row["runner_up_confidence"],
        "runner_up_source": row["runner_up_source"],
        "families": json.loads(row["families_json"] or "{}"),
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "search_context": json.loads(row["search_context_json"] or "{}"),
        "tags": json.loads(row["tags_json"] or "{}"),
        "auto_run_id": row["auto_run_id"],
        "auto_action_id": row["auto_action_id"],
    }


def row_to_decision_outcome(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "book_id": row["book_id"],
        "created_at": row["created_at"],
        "action": row["action"],
        "author": row["author"],
        "title": row["title"],
        "prev_author": row["prev_author"],
        "prev_title": row["prev_title"],
        "confidence_at_action": row["confidence_at_action"],
        "winning_source_at_action": row["winning_source_at_action"],
    }


def row_to_feedback(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "action_id": row["action_id"],
        "run_id": row["run_id"],
        "book_id": row["book_id"],
        "decision": row["decision"],
        "decided_at": row["decided_at"],
        "staged_author": row["staged_author"],
        "staged_title": row["staged_title"],
        "staged_path": row["staged_path"],
        "confidence": row["confidence"],
        "min_confidence": row["min_confidence"],
        "winning_source": row["winning_source"],
        "source_path": row["source_path"],
        "source_path_parts": json.loads(row["source_path_parts"]),
        "parent_context": row["parent_context"],
        "flatten_name": row["flatten_name"],
        "grouping": row["grouping"],
        "top_level_pack": row["top_level_pack"],
        "files": json.loads(row["files_json"]),
        "tags": json.loads(row["tags_json"] or "{}"),
        "candidates": _decode_candidates_payload(json.loads(row["candidates_json"] or "[]")),
        "search_context": json.loads(row["search_context_json"] or "{}"),
        "lookup_status": row["lookup_status"],
        "suggested_author": row["suggested_author"],
        "suggested_title": row["suggested_title"],
    }
