"""List and conflict reads for the 50,000-book bar.

D07: a generated book table is filtered and paged in SQL. The list response
does not include every row. Conflict and merge list construction does not
SELECT the whole books table twice per request.

Rows are inserted with SQL. This module does not create audio files and does
not use the network.
"""

from __future__ import annotations

import json

import app.main
from app.api import holder, list_books
from app.db import _utcnow
from tests.test_pin_flag_writes import _HolderFixture

_SCALE_ROWS = 50_000
_INSERT_BOOKS = """
INSERT INTO books (
    id, source_path, source_path_parts, top_level_pack, parent_context,
    grouping, flatten_name, flatten_target, files_json, status,
    suggested_author, suggested_title, suggested_series, suggested_series_index,
    suggested_series_state,
    chosen_author, chosen_title, chosen_series, chosen_series_index,
    chosen_author_set, chosen_title_set, chosen_series_set, chosen_series_index_set,
    confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending',
    ?, ?, '', '', 'confirmed',
    ?, ?, '', '',
    0, 0, 0, 0,
    0.5, '', '{}', '[]', 'ok', ?
)
"""


def _insert_generated_books(conn, count: int, *, needle_rows: int) -> None:
    now = _utcnow()
    rows = []
    for index in range(count):
        title = "Needle Unique" if index < needle_rows else f"Bulk {index}"
        source = f"src/{index}"
        rows.append(
            (
                f"b{index}",
                source,
                json.dumps([source]),
                "",
                "",
                "flat",
                title,
                "",
                "[]",
                "Author",
                title,
                "Author",
                title,
                now,
            )
        )
    conn.executemany(_INSERT_BOOKS, rows)
    conn.commit()


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split()).lower()


def _whole_books_reads(statements: list[str]) -> list[str]:
    found: list[str] = []
    for raw in statements:
        sql = _normalize_sql(raw)
        if not sql.startswith("select") or "from books" not in sql:
            continue
        if " where " in f" {sql} " or " limit " in f" {sql} ":
            continue
        if "count(" in sql:
            continue
        found.append(sql)
    return found


def _has_paged_books_read(statements: list[str]) -> bool:
    for raw in statements:
        sql = _normalize_sql(raw)
        if "from books" in sql and " where " in f" {sql} " and " limit " in f" {sql} ":
            return True
    return False


class _SqlTrace:
    def __init__(self, conn) -> None:
        self.conn = conn
        self.statements: list[str] = []

    def __enter__(self) -> list[str]:
        self.conn.set_trace_callback(self.statements.append)
        return self.statements

    def __exit__(self, *args) -> None:
        self.conn.set_trace_callback(None)


class ConflictMergeReadTests(_HolderFixture):
    def test_resolution_refresh_does_not_select_the_whole_books_table_twice(self) -> None:
        _insert_generated_books(self.conn, 4, needle_rows=1)

        with _SqlTrace(self.conn) as statements:
            holder.session.refresh_resolution_groups(self.conn)

        self.assertLess(len(_whole_books_reads(statements)), 2)


class BoundedListTests(_HolderFixture):
    def test_generated_rows_are_filtered_and_paged_in_sql(self) -> None:
        _insert_generated_books(self.conn, _SCALE_ROWS, needle_rows=20)
        indexed = self.conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'index' AND tbl_name = 'books' AND sql LIKE '%source_path%'
            """
        ).fetchone()
        self.assertIsNotNone(indexed)

        with _SqlTrace(self.conn) as statements:
            payload = list_books(
                status="pending",
                q="Needle",
                partitioned=True,
                limit=10,
                offset=0,
            )

        staging = payload["staging"]
        self.assertLessEqual(len(staging), 10)
        self.assertLess(len(staging), _SCALE_ROWS)
        self.assertTrue(staging)
        for book in staging:
            hay = " ".join(
                [
                    book.get("suggested_title") or "",
                    book.get("chosen_title") or "",
                    book.get("source_path") or "",
                ]
            )
            self.assertIn("Needle", hay)
        self.assertLess(len(payload["partial"]), _SCALE_ROWS)
        self.assertLess(len(payload["conflicts"]), _SCALE_ROWS)
        self.assertLess(len(payload["merges"]), _SCALE_ROWS)
        self.assertTrue(_has_paged_books_read(statements))
        self.assertLess(len(_whole_books_reads(statements)), 2)
