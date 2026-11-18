from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from stager_core.conflicts import (
    LIBRARY_SIDE_ID,
    resolve_winner_metadata,
)
from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.effective import (
    chosen_series_state,
    effective_author,
    effective_metadata,
    effective_series,
    effective_series_index,
    effective_title,
    target_key_preview,
)
from stager_core.metadata.lvi import (
    refresh_candidates_lvi,
    resolve_lvi_form_match,
)
from stager_core.metadata.duration import sum_file_durations, sum_library_target_durations
from stager_core.metadata.normalize import normalize_title
from stager_core.metadata.paths import resolve_seed_source_path
from stager_core.metadata.cleanup_pipeline import ADVANCED_UI_STEPS, validate_step_ids
from stager_core.metadata.query import build_search_context
from stager_core.metadata.tags import read_book_tags
from stager_core.metadata.title_extraction import (
    TitleExtractionConfig,
    ADVANCED_DEFAULT_POST,
    ADVANCED_DEFAULT_PRE,
    extract_title_with_source,
    resolve_advanced_steps,
)
from stager_core.metadata.types import ManualHints, TagInfo
from stager_core.staging import (
    BookResult,
    analyze_book_staging,
    complete_partial_stage,
    compute_target_key,
    remove_extra_library_files,
    replace_library_target,
    stage_book_author_title,
    resolve_merged_staged_names,
    stage_merged_books,
    unstage_book,
)

from app.activity_lock import get_activity_lock, renew_activity_lock
from app.auto import AutoRunAlreadyRunning, AutoRunBlocked, AutoRunManager
from app.db import (
    DB_LOCK,
    _utcnow,
    clear_conflict_resolution_for_key,
    delete_book_merges,
    dismiss_auto_actions_for_book,
    count_books,
    get_auto_settings,
    get_last_auto_run,
    get_session_meta,
    insert_decision_outcome,
    load_merged_members,
    record_auto_change_feedback,
    row_to_book,
    row_to_decision_outcome,
    row_to_feedback,
    row_to_lookup_decision,
    save_book_merge,
    save_conflict_resolution,
    update_auto_settings,
)
from app.scan import ScanAlreadyRunning, ScanManager
from app.scheduler import reschedule_auto_job
from app.session import STALE_SCAN_HOURS, StagingSession

router = APIRouter(prefix="/api")
_compute_conflicts_lock = threading.Lock()
HEALTH_DB_LOCK_TIMEOUT_S = 5.0
BULK_STAGE_MAX_WORKERS = min(8, os.cpu_count() or 4)


@dataclass(frozen=True)
class _ApproveStageJob:
    book_id: str
    book: FlatBook
    author: str
    title: str
    series: str
    series_index: str
    confidence: float


@dataclass
class _ApproveStageOutcome:
    job: _ApproveStageJob
    result: BookResult
    inode_index: dict[int, list[str]]


@dataclass(frozen=True)
class _RevertJob:
    book_id: str
    book: FlatBook
    staged_path: str
    author: str
    title: str
    confidence: float


@dataclass
class _RevertOutcome:
    job: _RevertJob
    result: BookResult


class ScanManagerHolder:
    manager: ScanManager | None = None
    auto_manager: AutoRunManager | None = None
    conn: sqlite3.Connection | None = None
    session: StagingSession | None = None
    scheduler_tick: Any = None


holder = ScanManagerHolder()


class BookPatch(BaseModel):
    chosen_author: str | None = None
    chosen_title: str | None = None
    chosen_series: str | None = None
    chosen_series_index: str | None = None
    status: str | None = None
    revert_fields: list[str] = Field(default_factory=list)
    revert_all: bool = False


class TargetKeyPreviewBody(BaseModel):
    chosen_author: str | None = None
    chosen_title: str | None = None
    chosen_series: str | None = None
    chosen_series_index: str | None = None


class LookupHints(BaseModel):
    author: str | None = None
    title: str | None = None


class BulkApprove(BaseModel):
    book_ids: list[str] = Field(default_factory=list)


class ConflictApprove(BaseModel):
    winner_side: str
    chosen_author: str | None = None
    chosen_title: str | None = None
    chosen_series: str | None = None
    chosen_series_index: str | None = None


class ConflictSeedEdit(BaseModel):
    book_id: str
    chosen_author: str = ""
    chosen_title: str = ""
    chosen_series: str = ""
    chosen_series_index: str = ""


class ConflictSaveEditsBody(BaseModel):
    edits: list[ConflictSeedEdit] = Field(default_factory=list)


class MergePreviewBody(BaseModel):
    member_book_ids: list[str] | None = None


class MergeApprove(BaseModel):
    primary_book_id: str | None = None
    member_book_ids: list[str] = Field(default_factory=list)
    chosen_author: str | None = None
    chosen_title: str | None = None
    chosen_series: str | None = None
    chosen_series_index: str | None = None
    staged_names: dict[str, str] = Field(default_factory=dict)


def _get_book_row(book_id: str) -> sqlite3.Row:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        row = holder.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "book not found")
    return row


def _flatbook_from_row(row: sqlite3.Row) -> FlatBook:
    files = [
        AudioFile(name=f["name"], source=f["source"], size_bytes=f["size_bytes"])
        for f in json.loads(row["files_json"])
    ]
    return FlatBook(
        id=row["id"],
        flatten_name=row["flatten_name"],
        source_path=row["source_path"],
        source_path_parts=json.loads(row["source_path_parts"]),
        top_level_pack=row["top_level_pack"],
        parent_context=row["parent_context"],
        grouping=row["grouping"],
        files=files,
        flatten_target=row["flatten_target"],
    )


def _all_book_rows() -> list[sqlite3.Row]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        return holder.conn.execute("SELECT * FROM books ORDER BY source_path").fetchall()


def _ensure_session() -> StagingSession:
    if holder.manager is None:
        raise HTTPException(500, "session not initialized")
    manager = holder.manager
    if holder.session is None or (
        holder.session.books_root != manager.books_root
        or holder.session.library_root != manager.library_root
    ):
        holder.session = StagingSession(manager.books_root, manager.library_root)
    return holder.session


def _lvi_form_match_for_metadata(author: str, series: str) -> dict[str, Any]:
    session = _ensure_session()
    return resolve_lvi_form_match(session.lvi, author, series).to_dict()


def _attach_lvi_form_match(book: dict[str, Any]) -> dict[str, Any]:
    session = _ensure_session()
    lvi = session.lvi
    book["lvi_form_match"] = resolve_lvi_form_match(
        lvi,
        book.get("effective_author") or "",
        book.get("effective_series") or "",
    ).to_dict()
    book["candidates"] = refresh_candidates_lvi(book.get("candidates") or [], lvi)
    return book


def _require_session_ready() -> StagingSession:
    session = _ensure_session()
    if not session.session_ready or session.stale:
        raise HTTPException(
            409,
            "Scan required before staging. Start a full scan to refresh library indexes.",
        )
    return session


def _inode_index_for_stage() -> dict[int, list[str]]:
    return _require_session_ready().get_inode_index_copy()


def _compute_conflicts() -> tuple[list[dict[str, Any]], set[str]]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    with _compute_conflicts_lock:
        session = _ensure_session()
        if holder.conn is not None:
            session.refresh_resolution_groups(holder.conn)
        return session.get_conflicts()


def _compute_merges() -> tuple[list[dict[str, Any]], set[str]]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    with _compute_conflicts_lock:
        session = _ensure_session()
        if holder.conn is not None:
            session.refresh_resolution_groups(holder.conn)
        return session.get_merges()


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _preview_row_from_body(row_data: dict[str, Any], body: TargetKeyPreviewBody) -> dict[str, Any]:
    virtual = dict(row_data)
    if body.chosen_author is not None:
        virtual["chosen_author"] = body.chosen_author
        virtual["chosen_author_set"] = 1
    if body.chosen_title is not None:
        virtual["chosen_title"] = body.chosen_title
        virtual["chosen_title_set"] = 1
    if body.chosen_series is not None:
        virtual["chosen_series"] = body.chosen_series
        virtual["chosen_series_set"] = 1
    if body.chosen_series_index is not None:
        virtual["chosen_series_index"] = body.chosen_series_index
        virtual["chosen_series_index_set"] = 1
    return virtual


def _row_target_key(row: sqlite3.Row) -> str:
    return target_key_preview(_row_dict(row))


def _resolve_stage_metadata(
    row: sqlite3.Row,
    book: FlatBook | None = None,
    *,
    override_author: str | None = None,
    override_title: str | None = None,
    override_series: str | None = None,
    override_series_index: str | None = None,
) -> tuple[str, str, str, str]:
    if book is None:
        book = _flatbook_from_row(row)
    row_data = _row_dict(row)
    return resolve_winner_metadata(
        chosen_author=row_data.get("chosen_author") or "",
        chosen_title=row_data.get("chosen_title") or "",
        suggested_author=row_data.get("suggested_author") or "",
        suggested_title=row_data.get("suggested_title") or "",
        flatten_name=book.flatten_name or "",
        chosen_author_set=int(row_data.get("chosen_author_set") or 0),
        chosen_title_set=int(row_data.get("chosen_title_set") or 0),
        chosen_series=row_data.get("chosen_series") or "",
        chosen_series_index=row_data.get("chosen_series_index") or "",
        chosen_series_set=int(row_data.get("chosen_series_set") or 0),
        chosen_series_index_set=int(row_data.get("chosen_series_index_set") or 0),
        suggested_series=row_data.get("suggested_series") or "",
        suggested_series_index=row_data.get("suggested_series_index") or "",
        suggested_series_state=row_data.get("suggested_series_state") or "unknown",
        override_author=override_author,
        override_title=override_title,
        override_series=override_series,
        override_series_index=override_series_index,
    )
def _book_in_conflict(book_id: str) -> bool:
    _, conflict_ids = _compute_conflicts()
    return book_id in conflict_ids


def _author_title_from_row(row: sqlite3.Row, book: FlatBook | None = None) -> tuple[str, str]:
    if book is None:
        book = _flatbook_from_row(row)
    row_data = _row_dict(row)
    return (
        effective_author(row_data),
        effective_title(row_data, flatten_name=book.flatten_name),
    )


def _library_names_from_path(staged_path_rel: str) -> tuple[str, str]:
    rel = (staged_path_rel or "").strip().replace("\\", "/")
    if "/" in rel:
        author_dir, title_dir = rel.split("/", 1)
        return author_dir, title_dir
    return "", rel


def _apply_partial_promotion(
    book_id: str,
    row: sqlite3.Row,
    book: FlatBook,
    staged_path_rel: str,
    *,
    action: str = "reconcile_partial",
) -> sqlite3.Row:
    if holder.conn is None or holder.manager is None:
        return row
    chosen_author, chosen_title, chosen_series, chosen_series_index = _resolve_stage_metadata(
        row, book
    )
    stage_result = BookResult(
        book_id=book.id,
        author=chosen_author,
        title=chosen_title,
        source_path=book.source_path,
        target_path=staged_path_rel,
        status="staged",
    )
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET
                status = 'staged', staged_path = ?, chosen_author = ?, chosen_title = ?,
                chosen_series = ?, chosen_series_index = ?,
                error = '', updated_at = ?
            WHERE id = ?
            """,
            (
                staged_path_rel,
                chosen_author,
                chosen_title,
                chosen_series,
                chosen_series_index,
                _utcnow(),
                book_id,
            ),
        )
        holder.conn.commit()
    session = _ensure_session()
    if session.session_ready:
        session.apply_stage(book, stage_result, holder.conn)
        session.refresh_conflicts(holder.conn)
    insert_decision_outcome(
        holder.conn,
        book_id=book_id,
        action=action,
        author=chosen_author,
        title=chosen_title,
        confidence_at_action=float(row["confidence"] or 0),
    )
    dismiss_auto_actions_for_book(holder.conn, book_id)
    return _get_book_row(book_id)


def _maybe_reconcile_partial_row(row: sqlite3.Row) -> sqlite3.Row:
    if row["status"] != "partial_staged":
        return row
    if holder.manager is None or holder.conn is None:
        return row
    session = _ensure_session()
    if not session.session_ready:
        return row
    book = _flatbook_from_row(row)
    author, title = _author_title_from_row(row, book)
    analysis = analyze_book_staging(
        holder.manager.books_root,
        book,
        session.get_inode_index_copy(),
        library_root=holder.manager.library_root,
        author=author,
        title=title,
        staged_path_rel=row["staged_path"] or "",
    )
    if analysis.detail != "already_staged":
        return row
    staged_path_rel = analysis.target_dir_rel or row["staged_path"] or ""
    if not staged_path_rel:
        return row
    return _apply_partial_promotion(row["id"], row, book, staged_path_rel)


def _staging_info_for_row(
    row: sqlite3.Row,
    *,
    include_files: bool = True,
) -> dict[str, Any] | None:
    if holder.manager is None:
        return None
    session = _ensure_session()
    if not session.session_ready:
        return None
    book = _flatbook_from_row(row)
    author, title = _author_title_from_row(row, book)
    analysis = analyze_book_staging(
        holder.manager.books_root,
        book,
        session.get_inode_index_copy(),
        library_root=holder.manager.library_root,
        author=author,
        title=title,
        staged_path_rel=row["staged_path"] or "",
    )
    return analysis.to_dict(include_files=include_files)


def _attach_staging_info(
    book: dict[str, Any],
    row: sqlite3.Row,
    *,
    include_files: bool = True,
) -> dict[str, Any]:
    if row["status"] != "partial_staged":
        return book
    staging = _staging_info_for_row(row, include_files=include_files)
    if staging is not None:
        book["staging"] = staging
    return book


def _attach_full_path(book: dict[str, Any], source_path: str) -> dict[str, Any]:
    if holder.manager is None:
        book["full_path"] = ""
        return book
    book["full_path"] = resolve_seed_source_path(holder.manager.books_root, source_path)
    return book


def _renew_lock(reason: str) -> None:
    if holder.conn is None:
        return
    with DB_LOCK:
        renew_activity_lock(holder.conn, reason)


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


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    checks = _run_health_checks()
    return {
        "status": _aggregate_health_status(checks),
        "version": request.app.version,
        "checks": checks,
    }


@router.get("/metadata/providers")
def get_metadata_providers() -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    return {"providers": holder.manager.lookup.provider_status()}


@router.post("/metadata/providers/test")
def test_metadata_providers() -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    return {"results": holder.manager.lookup.test_providers()}


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/session/status")
def get_session_status() -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")

    with DB_LOCK:
        meta = get_session_meta(holder.conn)
        last_completed = holder.conn.execute(
            """
            SELECT * FROM scans
            WHERE status = 'completed'
            ORDER BY finished_at DESC
            LIMIT 1
            """
        ).fetchone()
        book_count = count_books(holder.conn)

    scan_payload: dict[str, Any] | None = None
    auto_payload: dict[str, Any] | None = None
    state = "no_scan"

    if holder.auto_manager is not None and holder.auto_manager.is_running():
        row = holder.auto_manager.get_running_run()
        if row:
            auto_payload = dict(row)
            state = "auto_running"
    elif holder.manager is not None:
        row = holder.manager.get_running_scan()
        if row and holder.manager._thread is not None and holder.manager._thread.is_alive():
            scan_payload = _scan_row_to_api(row)
            state = "scan_running"

    if state not in {"auto_running", "scan_running"}:
        finished_at = meta.get("last_scan_finished_at")
        if last_completed is None and not finished_at:
            state = "no_scan"
        else:
            ref = finished_at or (last_completed["finished_at"] if last_completed else None)
            ref_dt = _parse_iso_dt(ref)
            if ref_dt is None:
                state = "no_scan"
            elif datetime.now(timezone.utc) - ref_dt > timedelta(hours=STALE_SCAN_HOURS):
                state = "stale_scan"
            else:
                book_n = meta.get("source_book_count") or book_count
                session = holder.session
                hydrated = bool(
                    session is not None and session.session_ready and not session.stale
                )
                if hydrated and book_n > 0:
                    state = "fresh"
                else:
                    state = "stale_scan"

    session = holder.session
    session_hydrated = bool(
        session is not None and session.session_ready and not session.stale
    )
    needs_scan = state in {"no_scan", "stale_scan"}

    return {
        "state": state,
        "needs_scan": needs_scan,
        "last_scan_finished_at": meta.get("last_scan_finished_at"),
        "last_source_discovery_at": meta.get("last_source_discovery_at"),
        "scan": scan_payload,
        "auto_run": auto_payload,
        "source_book_count": meta.get("source_book_count") or book_count,
        "library_target_count": meta.get("library_target_count") or 0,
        "session_hydrated": session_hydrated,
    }


@router.get("/scan/running")
def running_scan() -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    row = holder.manager.get_running_scan()
    if not row:
        return {"status": "none"}
    if holder.manager._thread is None or not holder.manager._thread.is_alive():
        return {"status": "none"}
    return _scan_row_to_api(row)


@router.get("/scan/latest")
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


@router.get("/scan/{scan_id}")
def get_scan(scan_id: str) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        row = holder.conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        raise HTTPException(404, "scan not found")
    return _scan_row_to_api(row)


@router.post("/scan/{scan_id}/cancel")
def cancel_scan(scan_id: str) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    if not holder.manager.cancel_scan(scan_id):
        raise HTTPException(409, "scan is not running")
    return {"cancelled": True, "scan_id": scan_id, "message": "Cancelling…"}


@router.post("/scan")
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


def _filter_books(
    rows: list[sqlite3.Row],
    *,
    status: str | None,
    q: str | None,
    low_confidence: bool,
    conflict_ids: set[str],
    section: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] == "partial_staged":
            row = _maybe_reconcile_partial_row(row)
        book = row_to_book(
            row,
            in_conflict=row["id"] in conflict_ids,
            target_key=_row_target_key(row),
        )
        if section == "staging":
            if book["in_conflict"] or book["status"] == "partial_staged":
                continue
            if not status or status == "pending":
                if book["status"] != "pending":
                    continue
        elif section == "partial":
            if book["status"] != "partial_staged":
                continue
        elif section == "conflicts":
            if not book["in_conflict"]:
                continue

        if status and status != "low_confidence" and book["status"] != status:
            continue
        if low_confidence and not (book["confidence"] < 0.7 and book["status"] == "pending"):
            continue
        if q:
            needle = q.lower()
            hay = " ".join(
                [
                    book["source_path"],
                    book.get("suggested_title") or "",
                    book.get("suggested_author") or "",
                    book.get("suggested_series") or "",
                    book.get("suggested_series_index") or "",
                    book.get("chosen_title") or "",
                    book.get("chosen_author") or "",
                    book.get("chosen_series") or "",
                    book.get("chosen_series_index") or "",
                    book.get("effective_series") or "",
                    book.get("effective_series_index") or "",
                ]
            ).lower()
            if needle not in hay:
                continue
        book = _attach_staging_info(book, row, include_files=False)
        items.append(_attach_lvi_form_match(book))
    return items


@router.get("/books")
def list_books(
    status: str | None = None,
    q: str | None = None,
    low_confidence: bool = False,
    section: str | None = None,
    partitioned: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")

    rows = _all_book_rows()
    groups, conflict_ids = _compute_conflicts()
    merge_groups, _merge_ids = _ensure_session().get_merges()

    with DB_LOCK:
        stats_rows = holder.conn.execute(
            "SELECT status, COUNT(*) AS c FROM books GROUP BY status"
        ).fetchall()
    stats = {r["status"]: r["c"] for r in stats_rows}
    stats["conflicts"] = len(groups)
    stats["conflict_books"] = len(conflict_ids)

    if partitioned:
        staging = _filter_books(
            rows, status=status, q=q, low_confidence=low_confidence,
            conflict_ids=conflict_ids, section="staging",
        )
        partial = _filter_books(
            rows, status=None, q=q, low_confidence=False,
            conflict_ids=conflict_ids, section="partial",
        )
        return {
            "conflicts": groups,
            "merges": merge_groups,
            "partial": partial,
            "staging": staging[offset : offset + limit],
            "stats": stats,
        }

    items = _filter_books(
        rows, status=status, q=q, low_confidence=low_confidence,
        conflict_ids=conflict_ids, section=section,
    )
    total = len(items)
    page = items[offset : offset + limit]
    return {"total": total, "items": page, "stats": stats, "conflicts": groups}


@router.get("/conflicts")
def list_conflicts() -> dict[str, Any]:
    groups, conflict_ids = _compute_conflicts()
    return {"groups": groups, "conflict_book_ids": sorted(conflict_ids)}


@router.get("/conflicts/{target_key:path}/duration")
def get_conflict_duration(target_key: str) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "not initialized")

    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    group = next((g for g in groups if g["target_key"] == key), None)
    if not group:
        raise HTTPException(404, "conflict group not found")

    sides_out: list[dict[str, Any]] = []
    for side in group["sides"]:
        if side["type"] == "seed":
            row = _get_book_row(side["book_id"])
            files = json.loads(row["files_json"])
            duration = sum_file_durations(files, holder.manager.books_root)
        else:
            duration = sum_library_target_durations(holder.manager.library_root, key)
        sides_out.append(
            {
                "side_id": side["side_id"],
                "total_duration_seconds": duration["total_duration_seconds"],
                "files": duration["files"],
            }
        )
    return {"target_key": key, "sides": sides_out}


@router.get("/conflicts/{target_key:path}")
def get_conflict(target_key: str) -> dict[str, Any]:
    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    for group in groups:
        if group["target_key"] == key:
            return group
    raise HTTPException(404, "conflict group not found")


@router.post("/conflicts/{target_key:path}/save-edits")
def save_conflict_edits(target_key: str, body: ConflictSaveEditsBody) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    if not body.edits:
        return {"saved": 0, "errors": [], "group": None}

    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    group = next((g for g in groups if g["target_key"] == key), None)

    errors: list[dict[str, str]] = []
    saved = 0
    now = _utcnow()
    with DB_LOCK:
        for edit in body.edits:
            row = holder.conn.execute(
                "SELECT id, status FROM books WHERE id = ?",
                (edit.book_id,),
            ).fetchone()
            if not row:
                errors.append({"book_id": edit.book_id, "error": "book not found"})
                continue
            if row["status"] != "pending":
                errors.append({"book_id": edit.book_id, "error": "book not editable"})
                continue
            holder.conn.execute(
                """
                UPDATE books SET
                    chosen_author = ?, chosen_title = ?,
                    chosen_series = ?, chosen_series_index = ?,
                    chosen_author_set = 1, chosen_title_set = 1,
                    chosen_series_set = 1, chosen_series_index_set = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    edit.chosen_author,
                    edit.chosen_title,
                    edit.chosen_series,
                    edit.chosen_series_index,
                    now,
                    edit.book_id,
                ),
            )
            saved += 1

        if saved:
            holder.conn.commit()
    if saved:
        _renew_lock("conflict_save_edits")

    groups, _ = _compute_conflicts()
    updated_group = next((g for g in groups if g["target_key"] == key), None)
    return {"saved": saved, "errors": errors, "group": updated_group}


@router.post("/conflicts/{target_key:path}/approve")
def approve_conflict(target_key: str, body: ConflictApprove) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    _renew_lock("conflict_approve")

    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    group = next((g for g in groups if g["target_key"] == key), None)
    if not group:
        raise HTTPException(404, "conflict group not found")

    winner = body.winner_side
    side_ids = {s["side_id"] for s in group["sides"]}
    if winner not in side_ids:
        raise HTTPException(400, "invalid winner_side")

    with DB_LOCK:
        save_conflict_resolution(holder.conn, key, winner)
        holder.conn.commit()

    seed_ids = [s["book_id"] for s in group["sides"] if s["type"] == "seed"]
    errors: list[dict[str, str]] = []

    if winner == LIBRARY_SIDE_ID:
        with DB_LOCK:
            for book_id in seed_ids:
                holder.conn.execute(
                    "UPDATE books SET status = 'skipped', error = '', updated_at = ? WHERE id = ?",
                    (_utcnow(), book_id),
                )
            holder.conn.commit()
        groups, _ = _compute_conflicts()
        merges, _ = _ensure_session().get_merges()
        return {"status": "resolved", "winner_side": winner, "conflicts": groups, "merges": merges, "errors": errors}

    row = _get_book_row(winner)
    book = _flatbook_from_row(row)
    has_overrides = (
        body.chosen_author is not None
        or body.chosen_title is not None
        or body.chosen_series is not None
        or body.chosen_series_index is not None
    )
    author, title, series, series_index = _resolve_stage_metadata(
        row,
        book,
        override_author=body.chosen_author,
        override_title=body.chosen_title,
        override_series=body.chosen_series,
        override_series_index=body.chosen_series_index,
    )
    if has_overrides:
        with DB_LOCK:
            holder.conn.execute(
                """
                UPDATE books SET
                    chosen_author = ?, chosen_title = ?,
                    chosen_series = ?, chosen_series_index = ?,
                    chosen_author_set = 1, chosen_title_set = 1,
                    chosen_series_set = 1, chosen_series_index_set = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (author, title, series, series_index, _utcnow(), winner),
            )
            holder.conn.commit()
    staging_key = compute_target_key(author, title, series, series_index)
    if group.get("has_library_side") and staging_key == key:
        replace_result = replace_library_target(holder.manager.library_root, author, title)
        if replace_result.status == "failed":
            raise HTTPException(400, replace_result.error or "library replacement failed")
        _ensure_session().apply_replace_library(author, title, holder.conn)
    inode_index = _inode_index_for_stage()
    result = stage_book_author_title(
        holder.manager.books_root,
        holder.manager.library_root,
        book,
        author,
        title,
        inode_index,
        dry_run=False,
        series=series,
        series_index=series_index,
    )

    if result.status in {"staged", "already_staged"}:
        with DB_LOCK:
            holder.conn.execute(
                """
                UPDATE books SET
                    status = ?, staged_path = ?, chosen_author = ?, chosen_title = ?,
                    chosen_series = ?, chosen_series_index = ?,
                    error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    "staged",
                    result.target_path,
                    author,
                    title,
                    series,
                    series_index,
                    "",
                    _utcnow(),
                    winner,
                ),
            )
            for book_id in seed_ids:
                if book_id == winner:
                    continue
                holder.conn.execute(
                    "UPDATE books SET status = 'skipped', error = '', updated_at = ? WHERE id = ?",
                    (_utcnow(), book_id),
                )
            holder.conn.commit()
    else:
        with DB_LOCK:
            holder.conn.execute(
                "UPDATE books SET error = ?, updated_at = ? WHERE id = ?",
                (result.error or result.status, _utcnow(), winner),
            )
            holder.conn.commit()
        msg = result.error or result.status
        if result.status == "name_collision":
            msg = (
                f"{msg}. Library files already occupy this path. "
                "Choose Library as winner or edit author/title to stage elsewhere."
            )
        raise HTTPException(400, msg)
    session = _ensure_session()
    if result.status in {"staged", "already_staged"}:
        session.merge_inode_index(inode_index)
        session.apply_stage(book, result, holder.conn)
    if holder.conn is not None:
        session.refresh_resolution_groups(holder.conn)

    groups, _ = session.get_conflicts()
    merges, _ = session.get_merges()
    return {"status": "resolved", "winner_side": winner, "conflicts": groups, "merges": merges, "errors": errors}


@router.post("/conflicts/{target_key:path}/merge/preview")
def preview_conflict_merge(target_key: str, body: MergePreviewBody | None = None) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "not initialized")

    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    group = next((g for g in groups if g["target_key"] == key), None)
    if not group:
        raise HTTPException(404, "conflict group not found")

    selected = _resolve_conflict_merge_selection(
        group,
        body.member_book_ids if body else None,
    )
    return _merge_preview_payload(group, selected, target_key=key)


@router.post("/conflicts/{target_key:path}/merge")
def approve_conflict_merge(target_key: str, body: MergeApprove) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    _renew_lock("conflict_merge_approve")

    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    group = next((g for g in groups if g["target_key"] == key), None)
    if not group:
        raise HTTPException(404, "conflict group not found")

    selected = _resolve_conflict_merge_selection(
        group,
        body.member_book_ids or None,
    )
    primary_book_id = body.primary_book_id or _pick_merge_primary(group, selected)
    eligible = set(group.get("merge_eligible_seed_ids") or [])
    skip_unselected = eligible - selected
    return _perform_merge(
        group,
        selected,
        primary_book_id,
        chosen_author=body.chosen_author,
        chosen_title=body.chosen_title,
        chosen_series=body.chosen_series,
        chosen_series_index=body.chosen_series_index,
        skip_unselected_seed_ids=skip_unselected,
        staged_names=body.staged_names,
    )


@router.get("/merges")
def list_merges() -> dict[str, Any]:
    groups, merge_ids = _compute_merges()
    return {"groups": groups, "merge_book_ids": sorted(merge_ids)}


@router.get("/merges/{target_key:path}")
def get_merge(target_key: str) -> dict[str, Any]:
    key = unquote(target_key)
    groups, _ = _compute_merges()
    for group in groups:
        if group["target_key"] == key:
            return group
    raise HTTPException(404, "merge group not found")


def _merge_candidates_from_group(group: dict[str, Any]) -> list[dict[str, Any]]:
    if "members" in group:
        return list(group.get("members") or [])
    return [s for s in group.get("sides") or [] if s.get("type") == "seed"]


def _merge_member_order(group: dict[str, Any], selected: set[str]) -> list[str]:
    if "member_book_ids" in group:
        order = list(group.get("member_book_ids") or [])
    else:
        order = [
            str(s["book_id"])
            for s in group.get("sides") or []
            if s.get("type") == "seed"
        ]
    return [book_id for book_id in order if book_id in selected]


def _pick_merge_primary(group: dict[str, Any], selected_ids: set[str]) -> str:
    candidates = _merge_candidates_from_group(group)
    selected_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.get("book_id") or candidate.get("side_id") or "") in selected_ids
    ]
    if not selected_candidates:
        raise HTTPException(400, "no selected members found")
    best = max(selected_candidates, key=lambda candidate: float(candidate.get("confidence") or 0))
    return str(best.get("book_id") or best.get("side_id") or "")


def _flatbooks_for_merge(
    group: dict[str, Any],
    selected: set[str],
    primary_book_id: str,
) -> tuple[FlatBook, list[FlatBook]]:
    ordered = _merge_member_order(group, selected)
    member_ids = [book_id for book_id in ordered if book_id != primary_book_id]
    primary_book = _flatbook_from_row(_get_book_row(primary_book_id))
    member_books = [_flatbook_from_row(_get_book_row(book_id)) for book_id in member_ids]
    return primary_book, member_books


def _merge_group_files(group: dict[str, Any], member_book_ids: set[str] | None = None) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for member in _merge_candidates_from_group(group):
        book_id = member.get("book_id")
        if member_book_ids is not None and book_id not in member_book_ids:
            continue
        combined.extend(member.get("files") or [])
    return combined


def _merge_preview_payload(
    group: dict[str, Any],
    selected: set[str],
    *,
    target_key: str,
) -> dict[str, Any]:
    primary_book_id = _pick_merge_primary(group, selected)
    primary_book, member_books = _flatbooks_for_merge(group, selected, primary_book_id)
    staged_files, filename_conflicts = resolve_merged_staged_names(primary_book, member_books)
    files = _merge_group_files(group, selected)
    duration = sum_file_durations(files, holder.manager.books_root)
    duration_counts: dict[int, int] = {}
    for entry in duration["files"]:
        seconds = int(entry.get("duration_seconds") or 0)
        if seconds > 0:
            duration_counts[seconds] = duration_counts.get(seconds, 0) + 1
    duplicate_durations = sorted(
        seconds for seconds, count in duration_counts.items() if count > 1
    )
    return {
        "target_key": target_key,
        "primary_book_id": primary_book_id,
        "member_book_ids": sorted(selected),
        "files": files,
        "staged_files": staged_files,
        "filename_conflicts": filename_conflicts,
        "total_duration_seconds": duration["total_duration_seconds"],
        "file_durations": duration["files"],
        "duplicate_duration_warning": bool(duplicate_durations),
        "duplicate_durations_seconds": duplicate_durations,
    }


def _resolve_merge_selection(
    group: dict[str, Any],
    *,
    primary_book_id: str | None,
    member_book_ids: list[str] | None,
) -> set[str]:
    group_ids = set(group["member_book_ids"])
    selected = set(member_book_ids) if member_book_ids else set(group_ids)
    if len(selected) < 2:
        raise HTTPException(400, "select at least two parts to merge")
    if not selected.issubset(group_ids):
        raise HTTPException(400, "member_book_ids contains ids not in merge group")
    if primary_book_id and primary_book_id not in selected:
        raise HTTPException(400, "primary_book_id must be included in member_book_ids")
    return selected


def _resolve_conflict_merge_selection(
    group: dict[str, Any],
    member_book_ids: list[str] | None,
) -> set[str]:
    eligible = set(group.get("merge_eligible_seed_ids") or [])
    if len(eligible) < 2:
        raise HTTPException(400, "conflict group has fewer than two merge-eligible seeds")
    selected = set(member_book_ids) if member_book_ids else set(eligible)
    if len(selected) < 2:
        raise HTTPException(400, "select at least two parts to merge")
    if not selected.issubset(eligible):
        raise HTTPException(400, "member_book_ids contains ids not eligible for merge")
    return selected


def _perform_merge(
    group: dict[str, Any],
    selected: set[str],
    primary_book_id: str,
    *,
    chosen_author: str | None,
    chosen_title: str | None,
    chosen_series: str | None = None,
    chosen_series_index: str | None = None,
    skip_unselected_seed_ids: set[str] | None = None,
    staged_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")

    key = group["target_key"]
    primary_row = _get_book_row(primary_book_id)
    if primary_row["status"] != "pending":
        raise HTTPException(400, "primary book must be pending")

    ordered = _merge_member_order(group, selected)
    member_rows: list[sqlite3.Row] = []
    for book_id in ordered:
        if book_id == primary_book_id:
            continue
        row = _get_book_row(book_id)
        if row["status"] != "pending":
            raise HTTPException(400, f"member {book_id} is not pending")
        member_rows.append(row)

    primary_book, member_books = _flatbooks_for_merge(group, selected, primary_book_id)
    has_overrides = (
        chosen_author is not None
        or chosen_title is not None
        or chosen_series is not None
        or chosen_series_index is not None
    )
    author, title, series, series_index = _resolve_stage_metadata(
        primary_row,
        primary_book,
        override_author=chosen_author,
        override_title=chosen_title,
        override_series=chosen_series,
        override_series_index=chosen_series_index,
    )

    combined_files = json.loads(primary_row["files_json"])
    existing_sources = {str(f.get("source") or "") for f in combined_files}
    for row in member_rows:
        for entry in json.loads(row["files_json"]):
            source = str(entry.get("source") or "")
            if source and source not in existing_sources:
                combined_files.append(entry)
                existing_sources.add(source)

    inode_index = _inode_index_for_stage()
    name_overrides = {
        source: name.strip()
        for source, name in (staged_names or {}).items()
        if name.strip()
    }
    result = stage_merged_books(
        holder.manager.books_root,
        holder.manager.library_root,
        primary_book,
        member_books,
        author,
        title,
        inode_index,
        staged_name_overrides=name_overrides if name_overrides else None,
        series=series,
        series_index=series_index,
    )
    if result.status not in {"staged", "already_staged"}:
        raise HTTPException(400, result.error or result.status)

    now = _utcnow()
    with DB_LOCK:
        if has_overrides:
            holder.conn.execute(
                """
                UPDATE books SET
                    chosen_author = ?, chosen_title = ?,
                    chosen_series = ?, chosen_series_index = ?,
                    chosen_author_set = 1, chosen_title_set = 1,
                    chosen_series_set = 1, chosen_series_index_set = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (author, title, series, series_index, now, primary_book_id),
            )
        holder.conn.execute(
            """
            UPDATE books SET
                status = ?, staged_path = ?, files_json = ?, chosen_author = ?, chosen_title = ?,
                chosen_series = ?, chosen_series_index = ?,
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                "staged",
                result.target_path,
                json.dumps(combined_files),
                author,
                title,
                series,
                series_index,
                "",
                now,
                primary_book_id,
            ),
        )
        for row in member_rows:
            holder.conn.execute(
                """
                UPDATE books SET status = 'merged', merged_into = ?, error = '', updated_at = ?
                WHERE id = ?
                """,
                (primary_book_id, now, row["id"]),
            )
            save_book_merge(holder.conn, primary_book_id, row["id"])
        if skip_unselected_seed_ids:
            for book_id in skip_unselected_seed_ids:
                holder.conn.execute(
                    "UPDATE books SET status = 'skipped', error = '', updated_at = ? WHERE id = ?",
                    (now, book_id),
                )
        holder.conn.commit()

    session = _ensure_session()
    session.merge_inode_index(inode_index)
    with DB_LOCK:
        updated_primary = holder.conn.execute(
            "SELECT * FROM books WHERE id = ?", (primary_book_id,)
        ).fetchone()
    merged_flatbook = _flatbook_from_row(updated_primary)
    session.apply_stage(merged_flatbook, result, holder.conn)
    session.refresh_resolution_groups(holder.conn)

    conflicts, _ = session.get_conflicts()
    merges, _ = session.get_merges()
    if not any(g["target_key"] == key for g in conflicts) and not any(
        g["target_key"] == key for g in merges
    ):
        with DB_LOCK:
            clear_conflict_resolution_for_key(holder.conn, key)
            holder.conn.commit()
    return {
        "status": "merged",
        "primary_book_id": primary_book_id,
        "target_key": key,
        "conflicts": conflicts,
        "merges": merges,
    }


@router.post("/merges/{target_key:path}/preview")
def preview_merge(target_key: str, body: MergePreviewBody | None = None) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "not initialized")

    key = unquote(target_key)
    groups, _ = _compute_merges()
    group = next((g for g in groups if g["target_key"] == key), None)
    if not group:
        raise HTTPException(404, "merge group not found")

    selected = _resolve_merge_selection(
        group,
        primary_book_id=None,
        member_book_ids=body.member_book_ids if body else None,
    )
    return _merge_preview_payload(group, selected, target_key=key)


@router.post("/merges/{target_key:path}")
def approve_merge(target_key: str, body: MergeApprove) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    _renew_lock("merge_approve")

    key = unquote(target_key)
    groups, _ = _compute_merges()
    group = next((g for g in groups if g["target_key"] == key), None)
    if not group:
        raise HTTPException(404, "merge group not found")

    selected = _resolve_merge_selection(
        group,
        primary_book_id=body.primary_book_id,
        member_book_ids=body.member_book_ids or None,
    )
    primary_book_id = body.primary_book_id or _pick_merge_primary(group, selected)
    return _perform_merge(
        group,
        selected,
        primary_book_id,
        chosen_author=body.chosen_author,
        chosen_title=body.chosen_title,
        chosen_series=body.chosen_series,
        chosen_series_index=body.chosen_series_index,
        staged_names=body.staged_names,
    )


@router.delete("/merges/{primary_book_id}")
def unmerge_books(primary_book_id: str) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    _renew_lock("merge_unmerge")

    with DB_LOCK:
        member_ids = load_merged_members(holder.conn, primary_book_id)
    if not member_ids:
        raise HTTPException(404, "no merge group for primary book")

    primary_row = _get_book_row(primary_book_id)
    primary_book = _flatbook_from_row(primary_row)

    if primary_row["status"] == "staged" and primary_row["staged_path"]:
        unstaged = unstage_book(
            holder.manager.books_root,
            holder.manager.library_root,
            primary_book,
            primary_row["staged_path"],
        )
        if unstaged.status not in {"unstaged", "not_staged"}:
            raise HTTPException(400, unstaged.error or unstaged.status)

    member_sources: set[str] = set()
    for member_id in member_ids:
        row = _get_book_row(member_id)
        for entry in json.loads(row["files_json"]):
            source = str(entry.get("source") or "")
            if source:
                member_sources.add(source)

    primary_files = [
        f for f in json.loads(primary_row["files_json"])
        if str(f.get("source") or "") not in member_sources
    ]
    now = _utcnow()
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET
                status = 'pending', staged_path = '', files_json = ?, error = '', updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(primary_files), now, primary_book_id),
        )
        for member_id in member_ids:
            holder.conn.execute(
                """
                UPDATE books SET status = 'pending', merged_into = '', error = '', updated_at = ?
                WHERE id = ?
                """,
                (now, member_id),
            )
        delete_book_merges(holder.conn, primary_book_id)
        holder.conn.commit()

    session = _ensure_session()
    if primary_row["status"] == "staged" and primary_row["staged_path"]:
        session.apply_unstage(primary_book, primary_row["staged_path"], holder.conn)
    session.refresh_resolution_groups(holder.conn)

    conflicts, _ = session.get_conflicts()
    merges, _ = session.get_merges()
    return {
        "status": "unmerged",
        "primary_book_id": primary_book_id,
        "member_book_ids": member_ids,
        "conflicts": conflicts,
        "merges": merges,
    }


@router.get("/books/{book_id}/duration")
def get_book_duration(book_id: str) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "not initialized")
    row = _get_book_row(book_id)
    files = json.loads(row["files_json"])
    return sum_file_durations(files, holder.manager.books_root)


@router.get("/books/{book_id}")
def get_book(book_id: str) -> dict[str, Any]:
    row = _get_book_row(book_id)
    row = _maybe_reconcile_partial_row(row)
    _, conflict_ids = _compute_conflicts()
    book = row_to_book(
        row,
        in_conflict=book_id in conflict_ids,
        target_key=_row_target_key(row),
    )
    return _attach_full_path(
        _attach_staging_info(_attach_lvi_form_match(book), row, include_files=True),
        row["source_path"],
    )


def _lookup_hints_to_manual(body: LookupHints | None) -> ManualHints | None:
    if body is None:
        return None
    manual = ManualHints(
        author=(body.author or "").strip(),
        title=(body.title or "").strip(),
    )
    if not any([manual.author, manual.title]):
        return None
    return manual


@router.patch("/books/{book_id}")
def patch_book(book_id: str, body: BookPatch) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    row = _get_book_row(book_id)
    row_data = _row_dict(row)
    prev_author = row_data.get("chosen_author") or ""
    prev_title = row_data.get("chosen_title") or ""
    chosen_author = (
        body.chosen_author
        if body.chosen_author is not None
        else row_data.get("chosen_author") or ""
    )
    chosen_title = (
        body.chosen_title
        if body.chosen_title is not None
        else row_data.get("chosen_title") or ""
    )
    chosen_series = (
        body.chosen_series
        if body.chosen_series is not None
        else row_data.get("chosen_series") or ""
    )
    chosen_series_index = (
        body.chosen_series_index
        if body.chosen_series_index is not None
        else row_data.get("chosen_series_index") or ""
    )
    status = body.status if body.status is not None else row["status"]
    metadata_changed = (body.chosen_author is not None or body.chosen_title is not None) and (
        chosen_author != prev_author or chosen_title != prev_title
    )
    author_set = int(row_data.get("chosen_author_set") or 0)
    title_set = int(row_data.get("chosen_title_set") or 0)
    series_set = int(row_data.get("chosen_series_set") or 0)
    series_index_set = int(row_data.get("chosen_series_index_set") or 0)
    if body.revert_all:
        author_set = title_set = series_set = series_index_set = 0
    else:
        for field_key in body.revert_fields:
            if field_key == "author":
                author_set = 0
            elif field_key == "title":
                title_set = 0
            elif field_key == "series":
                series_set = 0
            elif field_key == "series_index":
                series_index_set = 0
    if body.chosen_author is not None:
        author_set = 1
    if body.chosen_title is not None:
        title_set = 1
    if body.chosen_series is not None:
        series_value = (chosen_series or "").strip()
        suggested_value = (row_data.get("suggested_series") or "").strip()
        if series_value or suggested_value or series_set:
            series_set = 1
    if body.chosen_series_index is not None:
        index_value = (chosen_series_index or "").strip()
        suggested_index = (row_data.get("suggested_series_index") or "").strip()
        if index_value or suggested_index or series_index_set:
            series_index_set = 1
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET
                chosen_author = ?, chosen_title = ?,
                chosen_series = ?, chosen_series_index = ?,
                chosen_author_set = ?, chosen_title_set = ?,
                chosen_series_set = ?, chosen_series_index_set = ?,
                status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                chosen_author,
                chosen_title,
                chosen_series,
                chosen_series_index,
                author_set,
                title_set,
                series_set,
                series_index_set,
                status,
                _utcnow(),
                book_id,
            ),
        )
        holder.conn.commit()
    if metadata_changed:
        insert_decision_outcome(
            holder.conn,
            book_id=book_id,
            action="edit_metadata",
            author=chosen_author or "",
            title=chosen_title or "",
            prev_author=prev_author,
            prev_title=prev_title,
            confidence_at_action=float(row["confidence"] or 0),
        )
    _renew_lock("patch_book")
    return get_book(book_id)


@router.post("/books/{book_id}/target-key-preview")
def preview_book_target_key(book_id: str, body: TargetKeyPreviewBody) -> dict[str, Any]:
    row = _get_book_row(book_id)
    virtual = _preview_row_from_body(_row_dict(row), body)
    eff = effective_metadata(virtual)
    return {
        "target_key_preview": target_key_preview(virtual),
        "chosen_series_state": chosen_series_state(virtual),
        "lvi_form_match": _lvi_form_match_for_metadata(
            eff.get("effective_author") or "",
            eff.get("effective_series") or "",
        ),
    }


@router.post("/books/{book_id}/lookup")
def lookup_book(book_id: str, body: LookupHints | None = None) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "scan manager not initialized")
    manual = _lookup_hints_to_manual(body)
    holder.manager.lookup_book_by_id(book_id, manual=manual)
    _renew_lock("lookup")
    return get_book(book_id)


def _run_approve_stage_job(
    job: _ApproveStageJob,
    base_inode_index: dict[int, list[str]],
    books_root: Path,
    library_root: Path,
) -> _ApproveStageOutcome:
    inode_index = {ino: list(paths) for ino, paths in base_inode_index.items()}
    result = stage_book_author_title(
        books_root,
        library_root,
        job.book,
        job.author,
        job.title,
        inode_index,
        dry_run=False,
        series=job.series,
        series_index=job.series_index,
    )
    return _ApproveStageOutcome(job=job, result=result, inode_index=inode_index)


def _parallel_approve_stage_jobs(
    jobs: list[_ApproveStageJob],
    base_inode_index: dict[int, list[str]],
    books_root: Path,
    library_root: Path,
) -> list[_ApproveStageOutcome]:
    if not jobs:
        return []
    if len(jobs) == 1:
        return [_run_approve_stage_job(jobs[0], base_inode_index, books_root, library_root)]

    workers = min(BULK_STAGE_MAX_WORKERS, len(jobs))
    outcomes: list[_ApproveStageOutcome] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_run_approve_stage_job, job, base_inode_index, books_root, library_root)
            for job in jobs
        ]
        for future in futures:
            outcomes.append(future.result())
    return outcomes


def _commit_approve_book(
    book_id: str,
    row: sqlite3.Row,
    book: FlatBook,
    author: str,
    title: str,
    series: str,
    series_index: str,
    result: BookResult,
    *,
    inode_index: dict[int, list[str]] | None = None,
) -> str | None:
    new_status = "staged" if result.status in {"staged", "already_staged"} else result.status
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET
                status = ?, staged_path = ?, chosen_author = ?, chosen_title = ?,
                chosen_series = ?, chosen_series_index = ?,
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_status,
                result.target_path,
                author,
                title,
                series,
                series_index,
                result.error or "",
                _utcnow(),
                book_id,
            ),
        )
        holder.conn.commit()
    if result.status not in {"staged", "already_staged"} and new_status != "staged":
        return result.error or result.status
    session = _ensure_session()
    if result.status in {"staged", "already_staged"}:
        if inode_index is not None:
            session.merge_inode_index(inode_index)
        session.apply_stage(book, result, holder.conn)
        dismiss_auto_actions_for_book(holder.conn, book_id)
        insert_decision_outcome(
            holder.conn,
            book_id=book_id,
            action="approve",
            author=author,
            title=title,
            confidence_at_action=float(row["confidence"] or 0),
        )
    return None


@router.post("/books/{book_id}/approve")
def approve_book(book_id: str) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    if _book_in_conflict(book_id):
        raise HTTPException(400, "Resolve this book in the Conflicts section before approving.")
    row = _get_book_row(book_id)
    if row["status"] == "staged":
        return get_book(book_id)

    book = _flatbook_from_row(row)
    author, title, series, series_index = _resolve_stage_metadata(row, book)
    inode_index = _inode_index_for_stage()
    result = stage_book_author_title(
        holder.manager.books_root,
        holder.manager.library_root,
        book,
        author,
        title,
        inode_index,
        dry_run=False,
        series=series,
        series_index=series_index,
    )
    err = _commit_approve_book(
        book_id,
        row,
        book,
        author,
        title,
        series,
        series_index,
        result,
        inode_index=inode_index,
    )
    if err:
        raise HTTPException(400, err)
    session = _ensure_session()
    session.refresh_conflicts(holder.conn)
    _renew_lock("approve")
    return get_book(book_id)


@router.post("/books/{book_id}/complete-partial")
def complete_partial_book(book_id: str) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    if _book_in_conflict(book_id):
        raise HTTPException(400, "Resolve this book in the Conflicts section before linking.")
    row = _get_book_row(book_id)
    if row["status"] != "partial_staged":
        if row["status"] == "staged":
            return get_book(book_id)
        raise HTTPException(400, "book is not partially staged")

    book = _flatbook_from_row(row)
    author, title, series, series_index = _resolve_stage_metadata(row, book)
    inode_index = _inode_index_for_stage()
    result = complete_partial_stage(
        holder.manager.books_root,
        holder.manager.library_root,
        book,
        author,
        title,
        inode_index,
        row["staged_path"] or "",
        series=series,
        series_index=series_index,
    )
    new_status = "staged" if result.status == "staged" else "partial_staged"
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET
                status = ?, staged_path = ?, chosen_author = ?, chosen_title = ?,
                chosen_series = ?, chosen_series_index = ?,
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_status,
                result.target_path,
                author,
                title,
                series,
                series_index,
                "" if new_status == "staged" else (result.error or ""),
                _utcnow(),
                book_id,
            ),
        )
        holder.conn.commit()
    if result.status != "staged":
        raise HTTPException(400, result.error or result.status)
    session = _ensure_session()
    session.merge_inode_index(inode_index)
    session.apply_stage(book, result, holder.conn)
    dismiss_auto_actions_for_book(holder.conn, book_id)
    insert_decision_outcome(
        holder.conn,
        book_id=book_id,
        action="complete_partial",
        author=author,
        title=title,
        confidence_at_action=float(row["confidence"] or 0),
    )
    session.refresh_conflicts(holder.conn)
    _renew_lock("complete_partial")
    return get_book(book_id)


@router.post("/books/{book_id}/remove-extras")
def remove_extras_book(book_id: str) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    row = _get_book_row(book_id)
    if row["status"] != "partial_staged":
        raise HTTPException(400, "only partially staged books have removable extras")

    staging = _staging_info_for_row(row, include_files=False)
    if not staging or not staging.get("extra_library_files"):
        raise HTTPException(400, "no extra library files to remove")

    book = _flatbook_from_row(row)
    target_dir = staging.get("target_dir") or row["staged_path"] or ""
    session = _require_session_ready()
    inode_index = session.get_inode_index_copy()
    result = remove_extra_library_files(
        holder.manager.books_root,
        holder.manager.library_root,
        book,
        str(target_dir),
        inode_index,
    )
    if result.status not in {"removed_extras"}:
        raise HTTPException(400, result.error or result.status)

    session.inode_index = {ino: list(paths) for ino, paths in inode_index.items()}
    author, title = _author_title_from_row(row, book)
    post = analyze_book_staging(
        holder.manager.books_root,
        book,
        session.get_inode_index_copy(),
        library_root=holder.manager.library_root,
        author=author,
        title=title,
        staged_path_rel=str(target_dir),
    )
    new_status = "staged" if post.detail == "already_staged" else "partial_staged"
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET status = ?, staged_path = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_status,
                str(target_dir),
                "" if new_status == "staged" else row["error"] or "",
                _utcnow(),
                book_id,
            ),
        )
        holder.conn.commit()
    if new_status == "staged":
        stage_result = BookResult(
            book_id=book.id,
            author=result.target_path.split("/", 1)[0] if "/" in result.target_path else "",
            title=result.target_path.split("/", 1)[-1] if "/" in result.target_path else result.target_path,
            source_path=book.source_path,
            target_path=str(target_dir),
            status="staged",
        )
        session.apply_stage(book, stage_result, holder.conn)
    session.refresh_conflicts(holder.conn)
    _renew_lock("remove_extras")
    return get_book(book_id)


@router.post("/books/bulk-approve")
def bulk_approve(body: BulkApprove) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    _renew_lock("bulk_approve")
    _, conflict_ids = _compute_conflicts()
    results_by_id: dict[str, dict[str, Any]] = {}
    errors_by_id: dict[str, dict[str, str]] = {}
    jobs: list[_ApproveStageJob] = []
    job_rows: dict[str, sqlite3.Row] = {}

    for book_id in body.book_ids:
        if book_id in conflict_ids:
            errors_by_id[book_id] = {
                "book_id": book_id,
                "detail": "Resolve in Conflicts section before approving.",
            }
            continue
        try:
            row = _get_book_row(book_id)
        except HTTPException as exc:
            errors_by_id[book_id] = {"book_id": book_id, "detail": str(exc.detail)}
            continue
        if row["status"] == "staged":
            results_by_id[book_id] = get_book(book_id)
            continue
        book = _flatbook_from_row(row)
        author, title, series, series_index = _resolve_stage_metadata(row, book)
        jobs.append(
            _ApproveStageJob(
                book_id=book_id,
                book=book,
                author=author,
                title=title,
                series=series,
                series_index=series_index,
                confidence=float(row["confidence"] or 0),
            )
        )
        job_rows[book_id] = row

    if jobs:
        base_inode_index = _inode_index_for_stage()
        stage_outcomes = _parallel_approve_stage_jobs(
            jobs,
            base_inode_index,
            holder.manager.books_root,
            holder.manager.library_root,
        )
        for outcome in stage_outcomes:
            book_id = outcome.job.book_id
            row = job_rows[book_id]
            err = _commit_approve_book(
                book_id,
                row,
                outcome.job.book,
                outcome.job.author,
                outcome.job.title,
                outcome.job.series,
                outcome.job.series_index,
                outcome.result,
                inode_index=outcome.inode_index,
            )
            if err:
                errors_by_id[book_id] = {"book_id": book_id, "detail": err}
            else:
                results_by_id[book_id] = get_book(book_id)

        session = _ensure_session()
        session.refresh_conflicts(holder.conn)

    return {
        "approved": [results_by_id[book_id] for book_id in body.book_ids if book_id in results_by_id],
        "errors": [errors_by_id[book_id] for book_id in body.book_ids if book_id in errors_by_id],
    }


@router.post("/books/{book_id}/skip")
def skip_book(book_id: str) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    row = _get_book_row(book_id)
    with DB_LOCK:
        holder.conn.execute(
            "UPDATE books SET status = 'skipped', updated_at = ? WHERE id = ?",
            (_utcnow(), book_id),
        )
        holder.conn.commit()
    insert_decision_outcome(
        holder.conn,
        book_id=book_id,
        action="skip",
        author=row["chosen_author"] or row["suggested_author"] or "",
        title=row["chosen_title"] or row["suggested_title"] or "",
        confidence_at_action=float(row["confidence"] or 0),
    )
    _renew_lock("skip")
    return get_book(book_id)


@router.post("/books/{book_id}/unskip")
def unskip_book(book_id: str) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    row = _get_book_row(book_id)
    if row["status"] != "skipped":
        raise HTTPException(400, "only skipped books can be unskipped")
    with DB_LOCK:
        holder.conn.execute(
            "UPDATE books SET status = 'pending', error = '', updated_at = ? WHERE id = ?",
            (_utcnow(), book_id),
        )
        holder.conn.commit()
    insert_decision_outcome(
        holder.conn,
        book_id=book_id,
        action="unskip",
        author=row["chosen_author"] or row["suggested_author"] or "",
        title=row["chosen_title"] or row["suggested_title"] or "",
        confidence_at_action=float(row["confidence"] or 0),
    )
    _renew_lock("unskip")
    return get_book(book_id)


@router.post("/books/bulk-unskip")
def bulk_unskip(body: BulkApprove) -> dict[str, Any]:
    _renew_lock("bulk_unskip")
    results = []
    errors = []
    for book_id in body.book_ids:
        try:
            results.append(unskip_book(book_id))
        except HTTPException as exc:
            errors.append({"book_id": book_id, "detail": exc.detail})
    return {"unskipped": results, "errors": errors}


class AutoSettingsPatch(BaseModel):
    enabled: bool | None = None
    interval_hours: float | None = None
    min_confidence: float | None = None
    lock_timeout_minutes: int | None = None
    scan_manual_hints: bool | None = None
    lvi_search: bool | None = None
    lvi_boost: bool | None = None
    title_extraction_mode: str | None = None
    title_cleanup_pre: list[str] | None = None
    title_cleanup_post: list[str] | None = None


class TitleExtractionPreviewBody(BaseModel):
    mode: str = "balanced"
    pre_steps: list[str] = Field(default_factory=list)
    post_steps: list[str] = Field(default_factory=list)
    limit: int = 10
    book_ids: list[str] = Field(default_factory=list)


class AutoDismissBody(BaseModel):
    action_ids: list[str] = Field(default_factory=list)
    dismiss_all: bool = False


@router.get("/auto/settings")
def get_auto_settings_route() -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        settings = get_auto_settings(holder.conn)
        last_run = get_last_auto_run(holder.conn)
        lock = get_activity_lock(holder.conn)
    running = None
    if holder.auto_manager is not None and holder.auto_manager.is_running():
        row = holder.auto_manager.get_running_run()
        running = dict(row) if row else None
    return {
        "settings": settings,
        "last_run": last_run,
        "activity_lock": lock,
        "running": running,
    }


@router.patch("/auto/settings")
def patch_auto_settings(body: AutoSettingsPatch) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    fields = body.model_dump(exclude_none=True)
    if "min_confidence" in fields:
        conf = fields["min_confidence"]
        if conf < 0 or conf > 1:
            raise HTTPException(400, "min_confidence must be between 0 and 1")
    if "interval_hours" in fields and fields["interval_hours"] < 0.25:
        raise HTTPException(400, "interval_hours must be at least 0.25")
    if "lock_timeout_minutes" in fields and fields["lock_timeout_minutes"] < 1:
        raise HTTPException(400, "lock_timeout_minutes must be at least 1")
    mode = fields.get("title_extraction_mode")
    if mode is not None and mode not in ("conservative", "balanced", "advanced"):
        raise HTTPException(400, "title_extraction_mode must be conservative, balanced, or advanced")
    pre_steps = fields.pop("title_cleanup_pre", None)
    post_steps = fields.pop("title_cleanup_post", None)
    effective_mode = mode
    if effective_mode is None and (pre_steps is not None or post_steps is not None):
        with DB_LOCK:
            effective_mode = get_auto_settings(holder.conn).get("title_extraction_mode", "balanced")
    if effective_mode == "advanced" or (effective_mode is None and pre_steps is not None):
        try:
            if pre_steps is not None:
                validate_step_ids(pre_steps)
            if post_steps is not None:
                validate_step_ids(post_steps)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if mode in ("conservative", "balanced"):
        fields["title_cleanup_pre_json"] = "[]"
        fields["title_cleanup_post_json"] = "[]"
    elif mode == "advanced":
        if pre_steps is not None:
            fields["title_cleanup_pre_json"] = json.dumps(pre_steps)
        if post_steps is not None:
            fields["title_cleanup_post_json"] = json.dumps(post_steps)
        if pre_steps is None and post_steps is None:
            with DB_LOCK:
                current = get_auto_settings(holder.conn)
            if not current.get("title_cleanup_pre") and not current.get("title_cleanup_post"):
                fields["title_cleanup_pre_json"] = json.dumps(sorted(ADVANCED_DEFAULT_PRE))
                fields["title_cleanup_post_json"] = json.dumps(sorted(ADVANCED_DEFAULT_POST))
    else:
        if pre_steps is not None:
            fields["title_cleanup_pre_json"] = json.dumps(pre_steps)
        if post_steps is not None:
            fields["title_cleanup_post_json"] = json.dumps(post_steps)
    with DB_LOCK:
        settings = update_auto_settings(holder.conn, **fields)
    if "interval_hours" in fields and holder.scheduler_tick is not None:
        reschedule_auto_job(holder.scheduler_tick, settings["interval_hours"])
    return get_auto_settings_route()


def _tags_from_row(row: sqlite3.Row) -> TagInfo:
    raw = row["tags_json"] if "tags_json" in row.keys() else "{}"
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    if data:
        return TagInfo(
            title=data.get("title", ""),
            album=data.get("album", ""),
            artist=data.get("artist", ""),
            albumartist=data.get("albumartist", ""),
            asin=data.get("asin", ""),
            narrator=data.get("narrator", ""),
            raw=data.get("raw", {}),
        )
    if holder.manager is None:
        return TagInfo()
    files = json.loads(row["files_json"])
    file_sources = [f["source"] for f in files]
    return read_book_tags(holder.manager.books_root, file_sources)


def _title_extraction_config_from_body(body: TitleExtractionPreviewBody) -> TitleExtractionConfig:
    mode = (body.mode or "balanced").strip().lower()
    if mode not in ("conservative", "balanced", "advanced"):
        raise HTTPException(400, "mode must be conservative, balanced, or advanced")
    try:
        if mode == "advanced":
            pre, post = resolve_advanced_steps(body.pre_steps, body.post_steps)
        else:
            pre, post = frozenset(), frozenset()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return TitleExtractionConfig(mode=mode, pre_steps=pre, post_steps=post)


@router.post("/settings/title-extraction/preview")
def title_extraction_preview(body: TitleExtractionPreviewBody) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    limit = max(1, min(int(body.limit or 10), 25))
    config = _title_extraction_config_from_body(body)
    requested_ids = [str(book_id).strip() for book_id in (body.book_ids or []) if str(book_id).strip()]
    book_ids: list[str] = []
    with DB_LOCK:
        if requested_ids:
            placeholders = ",".join("?" for _ in requested_ids[:limit])
            rows = holder.conn.execute(
                f"""
                SELECT id FROM books
                WHERE id IN ({placeholders})
                  AND status IN ('pending', 'staged')
                """,
                requested_ids[:limit],
            ).fetchall()
            by_id = {r["id"]: r["id"] for r in rows}
            book_ids = [by_id[book_id] for book_id in requested_ids[:limit] if book_id in by_id]
        if not book_ids:
            pending_ids = [
                r["id"]
                for r in holder.conn.execute(
                    "SELECT id FROM books WHERE status = 'pending' ORDER BY RANDOM() LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
            remaining = limit - len(pending_ids)
            staged_ids: list[str] = []
            if remaining > 0:
                staged_ids = [
                    r["id"]
                    for r in holder.conn.execute(
                        "SELECT id FROM books WHERE status = 'staged' ORDER BY RANDOM() LIMIT ?",
                        (remaining,),
                    ).fetchall()
                ]
            book_ids = pending_ids + staged_ids

    samples: list[dict[str, Any]] = []
    for book_id in book_ids:
        row = _get_book_row(book_id)
        book = _flatbook_from_row(row)
        tags = _tags_from_row(row)
        context = build_search_context(book, tags, manual=None)
        current_title = normalize_title(context["title"]) or context["title"]
        extracted_title, source_used = extract_title_with_source(book, tags, config)
        extracted_title = normalize_title(extracted_title) or extracted_title
        label = book.flatten_name or book.source_path.rsplit("/", 1)[-1]
        samples.append({
            "book_id": book_id,
            "label": label,
            "status": row["status"],
            "raw_signals": {
                "album": (tags.album or "").strip(),
                "title": (tags.title or "").strip(),
                "file_stem": book.files[0].name.rsplit(".", 1)[0] if book.files else "",
            },
            "current_title": current_title,
            "extracted_title": extracted_title,
            "changed": current_title.strip().lower() != extracted_title.strip().lower(),
            "source_used": source_used,
        })
    return {
        "samples": samples,
        "advanced_steps": list(ADVANCED_UI_STEPS),
    }


@router.get("/auto/running")
def get_auto_running() -> dict[str, Any]:
    if holder.auto_manager is None:
        raise HTTPException(500, "auto manager not initialized")
    row = holder.auto_manager.get_running_run()
    if not row or not holder.auto_manager.is_running():
        return {"status": "none"}
    return dict(row)


@router.post("/auto/run")
def start_auto_run() -> dict[str, str]:
    if holder.auto_manager is None:
        raise HTTPException(500, "auto manager not initialized")
    try:
        run_id = holder.auto_manager.start_run(
            trigger="manual",
            require_enabled=False,
            bypass_activity_lock=True,
        )
    except AutoRunAlreadyRunning as exc:
        raise HTTPException(
            409,
            detail={"message": str(exc), "auto_run_id": exc.run_id, "kind": "auto_run"},
        ) from exc
    except AutoRunBlocked as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"run_id": run_id}


@router.post("/auto/{run_id}/cancel")
def cancel_auto_run(run_id: str) -> dict[str, Any]:
    if holder.auto_manager is None:
        raise HTTPException(500, "auto manager not initialized")
    if not holder.auto_manager.cancel_run(run_id):
        raise HTTPException(409, "auto-run is not active")
    return {"cancelled": True, "run_id": run_id}


@router.post("/auto/cache/clear")
def clear_metadata_cache() -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        holder.conn.execute("DELETE FROM api_cache")
        update_auto_settings(holder.conn, cache_relookup_pending=True)
        holder.conn.commit()
    _renew_lock("cache_clear")
    return {"status": "cleared", "cache_relookup_pending": True}


@router.get("/auto/review")
def get_auto_review() -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        rows = holder.conn.execute(
            """
            SELECT a.*, b.source_path AS book_source_path,
                   b.chosen_author, b.suggested_author, b.chosen_author_set,
                   b.chosen_title, b.suggested_title, b.chosen_title_set,
                   b.chosen_series, b.suggested_series, b.chosen_series_set,
                   b.chosen_series_index, b.suggested_series_index, b.chosen_series_index_set,
                   b.suggested_series_state, b.flatten_name
            FROM auto_actions a
            LEFT JOIN books b ON b.id = a.book_id
            WHERE a.dismissed_at IS NULL AND a.action = 'staged'
            ORDER BY a.created_at DESC
            """
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        if not item.get("source_path"):
            item["source_path"] = item.get("book_source_path") or ""
        eff = effective_metadata(row)
        item["effective_author"] = eff["effective_author"] or item.get("author") or ""
        item["effective_title"] = eff["effective_title"] or item.get("title") or ""
        item["effective_series"] = eff["effective_series"]
        item["effective_series_index"] = eff["effective_series_index"]
        item["target_key_preview"] = target_key_preview(row)
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/auto/review/dismiss")
def dismiss_auto_review(body: AutoDismissBody) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    now = _utcnow()
    with DB_LOCK:
        if body.dismiss_all:
            action_rows = holder.conn.execute(
                """
                SELECT id FROM auto_actions
                WHERE dismissed_at IS NULL AND action = 'staged'
                """
            ).fetchall()
            for action_row in action_rows:
                record_auto_change_feedback(
                    holder.conn,
                    action_id=action_row["id"],
                    decision="approved",
                )
            holder.conn.execute(
                """
                UPDATE auto_actions SET dismissed_at = ?
                WHERE dismissed_at IS NULL AND action = 'staged'
                """,
                (now,),
            )
        elif body.action_ids:
            for action_id in body.action_ids:
                record_auto_change_feedback(
                    holder.conn,
                    action_id=action_id,
                    decision="approved",
                )
            placeholders = ",".join("?" for _ in body.action_ids)
            holder.conn.execute(
                f"""
                UPDATE auto_actions SET dismissed_at = ?
                WHERE id IN ({placeholders}) AND dismissed_at IS NULL
                """,
                (now, *body.action_ids),
            )
        holder.conn.commit()
    _renew_lock("dismiss_review")
    return get_auto_review()


@router.get("/auto/feedback")
def get_auto_feedback(
    decision: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    if decision is not None and decision not in {"approved", "rejected"}:
        raise HTTPException(400, "decision must be approved or rejected")
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    with DB_LOCK:
        where = ""
        params: list[Any] = []
        if decision:
            where = "WHERE decision = ?"
            params.append(decision)
        total = holder.conn.execute(
            f"SELECT COUNT(*) AS count FROM auto_change_feedback {where}",
            params,
        ).fetchone()["count"]
        rows = holder.conn.execute(
            f"""
            SELECT * FROM auto_change_feedback
            {where}
            ORDER BY decided_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    return {
        "items": [row_to_feedback(row) for row in rows],
        "total": total,
    }


def _record_revert_action_feedback(book_id: str) -> None:
    with DB_LOCK:
        action_rows = holder.conn.execute(
            """
            SELECT id FROM auto_actions
            WHERE book_id = ? AND dismissed_at IS NULL
            """,
            (book_id,),
        ).fetchall()
        for action_row in action_rows:
            record_auto_change_feedback(
                holder.conn,
                action_id=action_row["id"],
                decision="rejected",
            )
        holder.conn.commit()


def _revert_job_from_row(row: sqlite3.Row) -> _RevertJob:
    if row["status"] not in {"staged", "partial_staged"}:
        raise HTTPException(400, "only staged or partially staged books can be reverted")
    book = _flatbook_from_row(row)
    return _RevertJob(
        book_id=row["id"],
        book=book,
        staged_path=row["staged_path"] or "",
        author=row["chosen_author"] or row["suggested_author"] or "",
        title=row["chosen_title"] or row["suggested_title"] or "",
        confidence=float(row["confidence"] or 0),
    )


def _run_revert_job(
    job: _RevertJob,
    books_root: Path,
    library_root: Path,
) -> _RevertOutcome:
    result = unstage_book(books_root, library_root, job.book, job.staged_path)
    return _RevertOutcome(job=job, result=result)


def _parallel_revert_jobs(
    jobs: list[_RevertJob],
    books_root: Path,
    library_root: Path,
) -> list[_RevertOutcome]:
    if not jobs:
        return []
    if len(jobs) == 1:
        return [_run_revert_job(jobs[0], books_root, library_root)]

    workers = min(BULK_STAGE_MAX_WORKERS, len(jobs))
    outcomes: list[_RevertOutcome] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_run_revert_job, job, books_root, library_root)
            for job in jobs
        ]
        for future in futures:
            outcomes.append(future.result())
    return outcomes


def _commit_revert_book(job: _RevertJob, result: BookResult) -> str | None:
    if result.status not in {"unstaged", "not_staged"}:
        return result.error or result.status
    with DB_LOCK:
        holder.conn.execute(
            """
            UPDATE books SET status = 'pending', staged_path = '', error = '', updated_at = ?
            WHERE id = ?
            """,
            (_utcnow(), job.book_id),
        )
        holder.conn.execute(
            """
            UPDATE auto_actions SET dismissed_at = ?
            WHERE book_id = ? AND dismissed_at IS NULL
            """,
            (_utcnow(), job.book_id),
        )
        holder.conn.commit()
    session = _ensure_session()
    session.apply_unstage(job.book, job.staged_path, holder.conn)
    insert_decision_outcome(
        holder.conn,
        book_id=job.book_id,
        action="revert",
        author=job.author,
        title=job.title,
        confidence_at_action=job.confidence,
    )
    return None


@router.post("/books/{book_id}/revert")
def revert_book(book_id: str) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    row = _get_book_row(book_id)
    job = _revert_job_from_row(row)
    _record_revert_action_feedback(book_id)
    outcome = _run_revert_job(job, holder.manager.books_root, holder.manager.library_root)
    err = _commit_revert_book(outcome.job, outcome.result)
    if err:
        raise HTTPException(400, err)
    session = _ensure_session()
    session.refresh_conflicts(holder.conn)
    _renew_lock("revert")
    return get_book(book_id)


@router.post("/books/bulk-revert")
def bulk_revert(body: BulkApprove) -> dict[str, Any]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    _renew_lock("bulk_revert")
    results_by_id: dict[str, dict[str, Any]] = {}
    errors_by_id: dict[str, dict[str, str]] = {}
    jobs: list[_RevertJob] = []

    for book_id in body.book_ids:
        try:
            row = _get_book_row(book_id)
            jobs.append(_revert_job_from_row(row))
        except HTTPException as exc:
            errors_by_id[book_id] = {"book_id": book_id, "detail": str(exc.detail)}

    for job in jobs:
        _record_revert_action_feedback(job.book_id)

    if jobs:
        outcomes = _parallel_revert_jobs(
            jobs,
            holder.manager.books_root,
            holder.manager.library_root,
        )
        for outcome in outcomes:
            err = _commit_revert_book(outcome.job, outcome.result)
            if err:
                errors_by_id[outcome.job.book_id] = {
                    "book_id": outcome.job.book_id,
                    "detail": err,
                }
            else:
                results_by_id[outcome.job.book_id] = get_book(outcome.job.book_id)

        session = _ensure_session()
        session.refresh_conflicts(holder.conn)

    return {
        "reverted": [results_by_id[book_id] for book_id in body.book_ids if book_id in results_by_id],
        "errors": [errors_by_id[book_id] for book_id in body.book_ids if book_id in errors_by_id],
    }


@router.get("/books/{book_id}/decisions")
def get_book_decisions(book_id: str, limit: int = 50) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    limit = min(max(limit, 1), 200)
    with DB_LOCK:
        decision_rows = holder.conn.execute(
            """
            SELECT * FROM lookup_decisions
            WHERE book_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (book_id, limit),
        ).fetchall()
        outcome_rows = holder.conn.execute(
            """
            SELECT * FROM decision_outcomes
            WHERE book_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (book_id, limit),
        ).fetchall()
    return {
        "book_id": book_id,
        "decisions": [row_to_lookup_decision(r) for r in decision_rows],
        "outcomes": [row_to_decision_outcome(r) for r in outcome_rows],
    }


@router.get("/decisions")
def list_decisions(
    since: str | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    limit = min(max(limit, 1), 1000)
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if source:
        clauses.append("winning_source = ?")
        params.append(source)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with DB_LOCK:
        total = holder.conn.execute(
            f"SELECT COUNT(*) AS count FROM lookup_decisions {where}",
            params,
        ).fetchone()["count"]
        rows = holder.conn.execute(
            f"""
            SELECT * FROM lookup_decisions
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return {
        "items": [row_to_lookup_decision(r) for r in rows],
        "total": total,
    }
