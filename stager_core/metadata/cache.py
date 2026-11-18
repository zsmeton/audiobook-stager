from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApiCache:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._lock = threading.Lock()

    def get(self, provider: str, cache_key: str) -> tuple[int, str] | None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT http_status, response_json, expires_at
                FROM api_cache
                WHERE provider = ? AND cache_key = ?
                """,
                (provider, cache_key),
            ).fetchone()
        if not row:
            return None
        status, body, expires_at = row
        if expires_at and expires_at < _utcnow():
            return None
        return int(status), str(body)

    def put(
        self,
        provider: str,
        cache_key: str,
        http_status: int,
        response_json: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO api_cache (provider, cache_key, response_json, http_status, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, cache_key) DO UPDATE SET
                  response_json = excluded.response_json,
                  http_status = excluded.http_status,
                  fetched_at = excluded.fetched_at,
                  expires_at = excluded.expires_at
                """,
                (provider, cache_key, response_json, http_status, _utcnow(), expires_at),
            )
            self.conn.commit()

    def put_permanent(self, provider: str, cache_key: str, http_status: int, payload: dict) -> None:
        self.put(provider, cache_key, http_status, json.dumps(payload), ttl_seconds=None)
