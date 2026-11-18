from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from stager_core.fingerprint import ALGO_VERSION, FingerprintCache

from app.db import DB_LOCK, _utcnow

_COMMIT_BATCH = 50


class OverlayFingerprintCache:
    """Thread-safe in-memory overlay in front of a persistent fingerprint cache."""

    def __init__(self, backend: FingerprintCache):
        self._backend = backend
        self._overlay: dict[tuple[str, int, int], str] = {}
        self._lock = threading.Lock()

    def get(self, rel_path: str, size_bytes: int, mtime_ns: int) -> str | None:
        key = (rel_path, size_bytes, mtime_ns)
        with self._lock:
            cached = self._overlay.get(key)
        if cached is not None:
            return cached
        cached = self._backend.get(rel_path, size_bytes, mtime_ns)
        if cached is not None:
            with self._lock:
                self._overlay[key] = cached
        return cached

    def put(
        self,
        rel_path: str,
        size_bytes: int,
        mtime_ns: int,
        fingerprint: str,
    ) -> None:
        key = (rel_path, size_bytes, mtime_ns)
        with self._lock:
            self._overlay[key] = fingerprint
        self._backend.put(rel_path, size_bytes, mtime_ns, fingerprint)

    def flush(self) -> None:
        self._backend.flush()


class SqliteFingerprintCache:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._pending_writes = 0

    def get(self, rel_path: str, size_bytes: int, mtime_ns: int) -> str | None:
        with DB_LOCK:
            row = self.conn.execute(
                """
                SELECT fingerprint
                FROM file_fingerprints
                WHERE rel_path = ? AND algo_version = ?
                  AND size_bytes = ? AND mtime_ns = ?
                """,
                (rel_path, ALGO_VERSION, size_bytes, mtime_ns),
            ).fetchone()
        if row is None:
            return None
        return str(row["fingerprint"])

    def put(
        self,
        rel_path: str,
        size_bytes: int,
        mtime_ns: int,
        fingerprint: str,
    ) -> None:
        with DB_LOCK:
            self.conn.execute(
                """
                INSERT INTO file_fingerprints (
                    rel_path, size_bytes, mtime_ns, algo_version,
                    fingerprint, computed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rel_path, algo_version) DO UPDATE SET
                    size_bytes = excluded.size_bytes,
                    mtime_ns = excluded.mtime_ns,
                    fingerprint = excluded.fingerprint,
                    computed_at = excluded.computed_at
                """,
                (
                    rel_path,
                    size_bytes,
                    mtime_ns,
                    ALGO_VERSION,
                    fingerprint,
                    _utcnow(),
                ),
            )
            self._pending_writes += 1
            if self._pending_writes >= _COMMIT_BATCH:
                self.conn.commit()
                self._pending_writes = 0

    def flush(self) -> None:
        with DB_LOCK:
            if self._pending_writes:
                self.conn.commit()
                self._pending_writes = 0

    def prune_missing(self, books_root: Path) -> int:
        with DB_LOCK:
            rows = self.conn.execute(
                """
                SELECT rel_path FROM file_fingerprints
                WHERE algo_version = ?
                """,
                (ALGO_VERSION,),
            ).fetchall()

        stale: list[str] = []
        for row in rows:
            rel_path = str(row["rel_path"])
            path = books_root / rel_path.replace("/", os.sep)
            if not path.is_file():
                stale.append(rel_path)

        if not stale:
            return 0

        with DB_LOCK:
            for i in range(0, len(stale), _COMMIT_BATCH):
                batch = stale[i : i + _COMMIT_BATCH]
                placeholders = ",".join("?" for _ in batch)
                self.conn.execute(
                    f"""
                    DELETE FROM file_fingerprints
                    WHERE algo_version = ? AND rel_path IN ({placeholders})
                    """,
                    (ALGO_VERSION, *batch),
                )
            self.conn.commit()
        return len(stale)
