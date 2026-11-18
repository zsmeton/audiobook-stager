from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import HTTPException

from app.db import DB_LOCK
from app.scan import ScanAlreadyRunning

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


def _scan_row_to_api(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    total = int(data.get("total_books") or 0)
    discovered = int(data.get("books_discovered") or data.get("books_found") or 0)
    complete = int(data.get("books_complete") or data.get("metadata_done") or 0)
    data["books_discovered"] = discovered
    data["books_found"] = discovered
    data["books_complete"] = complete
    data["metadata_done"] = complete
    data.setdefault("books_tagged", 0)
    data.setdefault("books_indexed", 0)
    data.setdefault("books_metadata", 0)
    data.setdefault("library_files_indexed", 0)
    data.setdefault("scan_phase", "")
    data["books_total"] = total
    data["metadata_total"] = total
    data["total_books"] = total
    return data

def running_scan() -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    row = holder.manager.get_running_scan()
    if not row:
        return {"status": "none"}
    if holder.manager._thread is None or not holder.manager._thread.is_alive():
        return {"status": "none"}
    return _scan_row_to_api(row)

def latest_scan() -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        row = holder.conn.execute(
            "SELECT * FROM scans ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"status": "none"}
    return _scan_row_to_api(row)

def get_scan(scan_id: str) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        row = holder.conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        raise HTTPException(404, "scan not found")
    return _scan_row_to_api(row)

def cancel_scan(scan_id: str) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    if not holder.manager.cancel_scan(scan_id):
        raise HTTPException(409, "scan is not running")
    return {"cancelled": True, "scan_id": scan_id, "message": "Cancelling…"}

def start_scan() -> dict[str, str]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    if holder.auto_manager is not None and holder.auto_manager.is_running():
        row = holder.auto_manager.get_running_run()
        raise HTTPException(
            409,
            detail={
                "message": "Auto-scan and stage in progress",
                "auto_run_id": row["id"] if row else None,
                "kind": "auto_run",
            },
        )
    try:
        scan_id = holder.manager.start_scan()
        _renew_lock("manual_scan")
    except ScanAlreadyRunning as exc:
        raise HTTPException(
            409,
            detail={"message": str(exc), "scan_id": exc.scan_id, "kind": "scan"},
        ) from exc
    return {"scan_id": scan_id}


# Last so app.api can re-export this module while it is still loading.
from app.services.books import _renew_lock

