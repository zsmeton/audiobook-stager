from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.db import DB_LOCK, _utcnow, ensure_auto_defaults, get_auto_settings


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def renew_activity_lock(conn: sqlite3.Connection, reason: str) -> dict[str, str]:
    with DB_LOCK:
        ensure_auto_defaults(conn)
        settings = get_auto_settings(conn)
        now = datetime.now(timezone.utc)
        locked_until = now + timedelta(minutes=settings["lock_timeout_minutes"])
        locked_until_iso = locked_until.isoformat()
        now_iso = now.isoformat()
        conn.execute(
            """
            UPDATE activity_lock
            SET locked_until = ?, last_renewed_at = ?, last_reason = ?
            WHERE id = 'default'
            """,
            (locked_until_iso, now_iso, reason),
        )
        conn.commit()
        return {
            "locked_until": locked_until_iso,
            "last_renewed_at": now_iso,
            "last_reason": reason,
        }


def get_activity_lock(conn: sqlite3.Connection) -> dict[str, str | bool]:
    ensure_auto_defaults(conn)
    row = conn.execute("SELECT * FROM activity_lock WHERE id = 'default'").fetchone()
    assert row is not None
    locked_until = row["locked_until"]
    active = _parse_iso(locked_until) > datetime.now(timezone.utc)
    return {
        "locked_until": locked_until,
        "last_renewed_at": row["last_renewed_at"],
        "last_reason": row["last_reason"] or "",
        "active": active,
    }


def is_activity_lock_active(conn: sqlite3.Connection) -> bool:
    return bool(get_activity_lock(conn)["active"])
