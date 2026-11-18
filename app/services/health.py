from __future__ import annotations

import sqlite3
import time
from typing import Any

from fastapi import Request

from app.activity_lock import get_activity_lock
from app.db import DB_LOCK

_state: Any = None


def bind_holder(state: Any) -> None:
    """Receive the startup holder. This module does not import it."""
    global _state
    _state = state


class _Holder:
    def __getattr__(self, name: str) -> Any:
        if _state is None:
            raise RuntimeError("app state is not initialized")
        return getattr(_state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if _state is None:
            raise RuntimeError("app state is not initialized")
        setattr(_state, name, value)


holder = _Holder()

HEALTH_DB_LOCK_TIMEOUT_S = 5.0


def _aggregate_health_status(checks: dict[str, dict[str, Any]]) -> str:
    statuses = [check.get("status", "ok") for check in checks.values()]
    if "error" in statuses:
        return "error"
    if "degraded" in statuses:
        return "degraded"
    return "ok"

def _run_health_checks() -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    running_scan_row: sqlite3.Row | None = None

    if holder.conn is None:
        checks["database"] = {
            "status": "error",
            "detail": "database not initialized",
        }
    else:
        db_check: dict[str, Any] = {"status": "ok"}
        lock_started = time.monotonic()
        acquired = DB_LOCK.acquire(timeout=HEALTH_DB_LOCK_TIMEOUT_S)
        lock_wait_ms = int((time.monotonic() - lock_started) * 1000)
        db_check["lock_wait_ms"] = lock_wait_ms
        if not acquired:
            db_check["status"] = "degraded"
            db_check["detail"] = (
                f"DB_LOCK not acquired within {int(HEALTH_DB_LOCK_TIMEOUT_S)}s"
            )
        else:
            try:
                holder.conn.execute("SELECT 1").fetchone()
                integrity = holder.conn.execute("PRAGMA quick_check").fetchone()
                if integrity and integrity[0] != "ok":
                    db_check["status"] = "error"
                    db_check["integrity"] = integrity[0]
                else:
                    db_check["integrity"] = "ok"
                lock = get_activity_lock(holder.conn)
                checks["activity_lock"] = {
                    "status": "ok",
                    "active": bool(lock["active"]),
                    "last_reason": lock.get("last_reason") or "",
                }
                running_scan_row = holder.conn.execute(
                    """
                    SELECT * FROM scans
                    WHERE status = 'running'
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                DB_LOCK.release()
        checks["database"] = db_check

    scan_check: dict[str, Any] = {"status": "ok", "running": False}
    manager = holder.manager
    thread_alive = (
        manager is not None
        and manager._thread is not None
        and manager._thread.is_alive()
    )
    if running_scan_row and thread_alive:
        scan_check["running"] = True
        scan_check["scan_id"] = running_scan_row["id"]
        total = int(running_scan_row["total_books"] or 0)
        discovered = int(
            running_scan_row["books_discovered"] or running_scan_row["books_found"] or 0
        )
        complete = int(
            running_scan_row["books_complete"] or running_scan_row["metadata_done"] or 0
        )
        scan_check["books_found"] = discovered
        scan_check["books_discovered"] = discovered
        scan_check["books_complete"] = complete
        scan_check["total_books"] = total
        phase = (running_scan_row["scan_phase"] or "").strip()
        if phase:
            scan_check["phase"] = phase
        else:
            scan_check["phase"] = "discovery" if total == 0 else "metadata"
        scan_check["message"] = running_scan_row["message"] or ""
    checks["scan"] = scan_check

    if "activity_lock" not in checks:
        checks["activity_lock"] = {
            "status": "degraded" if holder.conn is None else "ok",
            "active": False,
            "detail": "skipped (database unavailable)" if holder.conn is None else "",
        }

    return checks

def health(request: Request) -> dict[str, Any]:
    checks = _run_health_checks()
    return {
        "status": _aggregate_health_status(checks),
        "version": request.app.version,
        "checks": checks,
    }

