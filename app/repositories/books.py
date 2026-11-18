"""Paged book lists and the shared conflict/merge read.

Conflict and merge detection still need every eligible book (not staged,
skipped, partial, or merged). That read is one filtered statement, shared by
both detectors. List pages add WHERE and LIMIT so the handler does not load
the table and filter it in Python.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db import DB_LOCK

_ID_FILTER = "book_list_id_filter"
_MAX_INLINE_IDS = 500

_RESOLUTION_SQL = """
SELECT * FROM books
WHERE COALESCE(status, '') NOT IN ('staged', 'skipped', 'partial_staged', 'merged')
ORDER BY source_path
"""

_EFFECTIVE_SERIES = """
CASE
  WHEN COALESCE(chosen_series_set, 0) != 0 THEN TRIM(COALESCE(chosen_series, ''))
  WHEN TRIM(COALESCE(suggested_series, '')) != ''
    OR TRIM(COALESCE(suggested_series_index, '')) != ''
    THEN TRIM(COALESCE(suggested_series, ''))
  ELSE TRIM(COALESCE(json_extract(candidates_json, '$[0].series'), ''))
END
""".strip()

_EFFECTIVE_SERIES_INDEX = """
CASE
  WHEN COALESCE(chosen_series_index_set, 0) != 0 THEN TRIM(COALESCE(chosen_series_index, ''))
  WHEN TRIM(COALESCE(suggested_series, '')) != ''
    OR TRIM(COALESCE(suggested_series_index, '')) != ''
    THEN TRIM(COALESCE(suggested_series_index, ''))
  ELSE TRIM(COALESCE(json_extract(candidates_json, '$[0].series_index'), ''))
END
""".strip()

_SEARCH_SQL = f"""
INSTR(LOWER(
  COALESCE(source_path, '') || ' ' ||
  COALESCE(suggested_title, '') || ' ' ||
  COALESCE(suggested_author, '') || ' ' ||
  COALESCE(suggested_series, '') || ' ' ||
  COALESCE(suggested_series_index, '') || ' ' ||
  COALESCE(chosen_title, '') || ' ' ||
  COALESCE(chosen_author, '') || ' ' ||
  COALESCE(chosen_series, '') || ' ' ||
  COALESCE(chosen_series_index, '') || ' ' ||
  ({_EFFECTIVE_SERIES}) || ' ' ||
  ({_EFFECTIVE_SERIES_INDEX})
), LOWER(?)) > 0
""".strip()


def fetch_resolution_book_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Eligible books for conflict and merge detection, ordered by source_path."""
    with DB_LOCK:
        return conn.execute(_RESOLUTION_SQL).fetchall()


def book_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    with DB_LOCK:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM books GROUP BY status"
        ).fetchall()
    return {row["status"]: row["c"] for row in rows}


def fetch_book_page(
    conn: sqlite3.Connection,
    *,
    section: str | None,
    status: str | None,
    q: str | None,
    low_confidence: bool,
    conflict_ids: set[str],
    limit: int,
    offset: int,
) -> list[sqlite3.Row]:
    page_limit, page_offset = _page_bounds(limit, offset)
    with DB_LOCK:
        where, params = _filtered_where(
            conn,
            section=section,
            status=status,
            q=q,
            low_confidence=low_confidence,
            conflict_ids=conflict_ids,
        )
        params.extend((page_limit, page_offset))
        return conn.execute(
            f"SELECT * FROM books {where} ORDER BY source_path LIMIT ? OFFSET ?",
            params,
        ).fetchall()


def count_filtered_books(
    conn: sqlite3.Connection,
    *,
    section: str | None,
    status: str | None,
    q: str | None,
    low_confidence: bool,
    conflict_ids: set[str],
) -> int:
    with DB_LOCK:
        where, params = _filtered_where(
            conn,
            section=section,
            status=status,
            q=q,
            low_confidence=low_confidence,
            conflict_ids=conflict_ids,
        )
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM books {where}",
            params,
        ).fetchone()
    return int(row["c"]) if row else 0


def _page_bounds(limit: int, offset: int) -> tuple[int, int]:
    # SQLite treats a negative LIMIT as "no limit".
    page_limit = limit if isinstance(limit, int) and limit > 0 else 0
    page_offset = offset if isinstance(offset, int) and offset > 0 else 0
    return page_limit, page_offset


def _filtered_where(
    conn: sqlite3.Connection,
    *,
    section: str | None,
    status: str | None,
    q: str | None,
    low_confidence: bool,
    conflict_ids: set[str],
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if section == "staging":
        clauses.append("status != 'partial_staged'")
        if not status or status == "pending":
            clauses.append("status = 'pending'")
    elif section == "partial":
        clauses.append("status = 'partial_staged'")

    id_sql, id_params = _id_clause(
        conn,
        conflict_ids,
        mode=_id_mode(section),
    )
    if id_sql:
        clauses.append(id_sql)
        params.extend(id_params)

    status_already_applied = section == "staging" and (not status or status == "pending")
    partial_status_already_applied = section == "partial" and status == "partial_staged"
    if (
        status
        and status != "low_confidence"
        and not status_already_applied
        and not partial_status_already_applied
    ):
        clauses.append("status = ?")
        params.append(status)

    if low_confidence:
        clauses.append("COALESCE(confidence, 0) < 0.7")
        clauses.append("status = 'pending'")

    if q:
        clauses.append(_SEARCH_SQL)
        params.append(q)

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _id_mode(section: str | None) -> str:
    if section == "staging":
        return "exclude"
    if section == "conflicts":
        return "include"
    return "none"


def _id_clause(
    conn: sqlite3.Connection,
    ids: set[str],
    *,
    mode: str,
) -> tuple[str, list[Any]]:
    if mode == "none":
        return "", []
    if not ids:
        if mode == "include":
            return "0", []
        return "", []
    op = "IN" if mode == "include" else "NOT IN"
    if len(ids) <= _MAX_INLINE_IDS:
        marks = ",".join("?" for _ in ids)
        return f"id {op} ({marks})", list(ids)
    _fill_id_filter(conn, ids)
    return f"id {op} (SELECT id FROM {_ID_FILTER})", []


def _fill_id_filter(conn: sqlite3.Connection, ids: set[str]) -> None:
    conn.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {_ID_FILTER} (id TEXT PRIMARY KEY)"
    )
    conn.execute(f"DELETE FROM {_ID_FILTER}")
    conn.executemany(
        f"INSERT OR IGNORE INTO {_ID_FILTER} (id) VALUES (?)",
        ((book_id,) for book_id in ids),
    )
