from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from stager_core.metadata.cleanup_pipeline import ADVANCED_UI_STEPS
from stager_core.metadata.normalize import normalize_title
from stager_core.metadata.query import build_search_context
from stager_core.metadata.tags import read_book_tags
from stager_core.metadata.title_extraction import (
    TitleExtractionConfig,
    extract_title_with_source,
    resolve_advanced_steps,
)
from stager_core.metadata.types import TagInfo

from app.auto import AutoRunManager
from app.db import DB_LOCK, count_books, get_session_meta, row_to_lookup_decision
from app.scan import ScanManager
from app.session import STALE_SCAN_HOURS, StagingSession

router = APIRouter(prefix="/api")


class ScanManagerHolder:
    manager: ScanManager | None = None
    auto_manager: AutoRunManager | None = None
    conn: sqlite3.Connection | None = None
    session: StagingSession | None = None
    scheduler_tick: Any = None

# The startup object from app.main. Tests patch this name; it is not a second instance.
holder: ScanManagerHolder | None = None

class TitleExtractionPreviewBody(BaseModel):
    mode: str = "balanced"
    pre_steps: list[str] = Field(default_factory=list)
    post_steps: list[str] = Field(default_factory=list)
    limit: int = 10
    book_ids: list[str] = Field(default_factory=list)

from app.services.books import (
    BULK_STAGE_MAX_WORKERS,
    _compute_conflicts_lock,
    _ApproveStageJob,
    _ApproveStageOutcome,
    _RevertJob,
    _RevertOutcome,
    BookPatch,
    TargetKeyPreviewBody,
    LookupHints,
    BulkApprove,
    _get_book_row,
    _flatbook_from_row,
    _ensure_session,
    _lvi_form_match_for_metadata,
    _attach_lvi_form_match,
    _require_session_ready,
    _inode_index_for_stage,
    _row_dict,
    _preview_row_from_body,
    _row_target_key,
    _resolve_stage_metadata,
    _book_in_conflict,
    _author_title_from_row,
    _library_names_from_path,
    _apply_partial_promotion,
    _maybe_reconcile_partial_row,
    _staging_info_for_row,
    _attach_staging_info,
    _attach_full_path,
    _renew_lock,
    _page_limit,
    _rows_to_books,
    list_books,
    get_book_duration,
    get_book,
    _lookup_hints_to_manual,
    patch_book,
    preview_book_target_key,
    lookup_book,
    _run_approve_stage_job,
    _parallel_approve_stage_jobs,
    _commit_approve_book,
    approve_book,
    complete_partial_book,
    remove_extras_book,
    bulk_approve,
    skip_book,
    unskip_book,
    bulk_unskip,
    _record_revert_action_feedback,
    _revert_job_from_row,
    _run_revert_job,
    _parallel_revert_jobs,
    _commit_revert_book,
    revert_book,
    bulk_revert,
    get_book_decisions,
)

from app.services.conflicts import (
    ConflictApprove,
    ConflictSeedEdit,
    ConflictSaveEditsBody,
    _compute_conflicts,
    list_conflicts,
    get_conflict_duration,
    get_conflict,
    save_conflict_edits,
    approve_conflict,
    preview_conflict_merge,
    approve_conflict_merge,
    _resolve_conflict_merge_selection,
)

from app.services.merges import (
    MergePreviewBody,
    MergeApprove,
    _compute_merges,
    list_merges,
    get_merge,
    _merge_candidates_from_group,
    _merge_member_order,
    _pick_merge_primary,
    _flatbooks_for_merge,
    _merge_group_files,
    _merge_preview_payload,
    _resolve_merge_selection,
    _perform_merge,
    preview_merge,
    approve_merge,
    unmerge_books,
)

from app.services.scan import (
    _scan_row_to_api,
    running_scan,
    latest_scan,
    get_scan,
    cancel_scan,
    start_scan,
)

from app.services.health import (
    HEALTH_DB_LOCK_TIMEOUT_S,
    _aggregate_health_status,
    _run_health_checks,
    health,
)

from app.services.auto import (
    AutoSettingsPatch,
    AutoDismissBody,
    get_auto_settings_route,
    patch_auto_settings,
    get_auto_running,
    start_auto_run,
    cancel_auto_run,
    clear_metadata_cache,
    get_auto_review,
    dismiss_auto_review,
    get_auto_feedback,
)

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

