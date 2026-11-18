from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stager_core.conflicts import resolve_winner_metadata
from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.duration import sum_file_durations
from stager_core.metadata.effective import (
    chosen_series_state,
    effective_author,
    effective_metadata,
    effective_title,
    target_key_preview,
)
from stager_core.metadata.lvi import refresh_candidates_lvi, resolve_lvi_form_match
from stager_core.metadata.paths import resolve_seed_source_path
from stager_core.metadata.types import ManualHints
from stager_core.staging import (
    BookResult,
    analyze_book_staging,
    complete_partial_stage,
    remove_extra_library_files,
    stage_book_author_title,
    unstage_book,
)

from app.activity_lock import renew_activity_lock
from app.db import (
    DB_LOCK,
    _utcnow,
    dismiss_auto_actions_for_book,
    insert_decision_outcome,
    record_auto_change_feedback,
    row_to_book,
    row_to_decision_outcome,
    row_to_lookup_decision,
)
from app.repositories.books import book_status_counts, count_filtered_books, fetch_book_page
from app.session import StagingSession

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

_compute_conflicts_lock = threading.Lock()
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
    from app.services.conflicts import _compute_conflicts

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

def _page_limit(limit: int) -> int:
    return limit if isinstance(limit, int) and limit > 0 else 0

def _rows_to_books(
    rows: list[sqlite3.Row],
    conflict_ids: set[str],
    *,
    reconcile_partial: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if reconcile_partial and row["status"] == "partial_staged":
            row = _maybe_reconcile_partial_row(row)
            if row["status"] != "partial_staged":
                continue
        book = row_to_book(
            row,
            in_conflict=row["id"] in conflict_ids,
            target_key=_row_target_key(row),
        )
        items.append(
            _attach_lvi_form_match(_attach_staging_info(book, row, include_files=False))
        )
    return items

def list_books(
    status: str | None = None,
    q: str | None = None,
    low_confidence: bool = False,
    section: str | None = None,
    partitioned: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    from app.services.conflicts import _compute_conflicts

    if holder.conn is None:
        raise HTTPException(500, "database not initialized")

    groups, conflict_ids = _compute_conflicts()
    merge_groups, merge_ids = _ensure_session().get_merges()
    stats = book_status_counts(holder.conn)
    stats["conflicts"] = len(groups)
    stats["conflict_books"] = len(conflict_ids)
    capped = _page_limit(limit)
    # Seed/seed duplicates are conflicts and merges. The page hides merge
    # members itself. Library conflicts are not merges, and stay out of staging.
    staging_conflict_ids = conflict_ids - merge_ids

    if partitioned:
        partial_rows = fetch_book_page(
            holder.conn,
            section="partial",
            status=None,
            q=q,
            low_confidence=False,
            conflict_ids=conflict_ids,
            limit=capped,
            offset=0,
        )
        partial = _rows_to_books(partial_rows, conflict_ids, reconcile_partial=True)
        staging_rows = fetch_book_page(
            holder.conn,
            section="staging",
            status=status,
            q=q,
            low_confidence=low_confidence,
            conflict_ids=staging_conflict_ids,
            limit=capped,
            offset=offset,
        )
        return {
            "conflicts": groups[:capped],
            "merges": merge_groups[:capped],
            "partial": partial,
            "staging": _rows_to_books(
                staging_rows, conflict_ids, reconcile_partial=False
            ),
            "stats": stats,
        }

    list_conflict_ids = staging_conflict_ids if section == "staging" else conflict_ids
    total = count_filtered_books(
        holder.conn,
        section=section,
        status=status,
        q=q,
        low_confidence=low_confidence,
        conflict_ids=list_conflict_ids,
    )
    rows = fetch_book_page(
        holder.conn,
        section=section,
        status=status,
        q=q,
        low_confidence=low_confidence,
        conflict_ids=list_conflict_ids,
        limit=capped,
        offset=offset,
    )
    return {
        "total": total,
        "items": _rows_to_books(rows, conflict_ids, reconcile_partial=True),
        "stats": stats,
        "conflicts": groups[:capped],
    }

def get_book_duration(book_id: str) -> dict[str, Any]:
    if holder.manager is None:
        raise HTTPException(500, "not initialized")
    row = _get_book_row(book_id)
    files = json.loads(row["files_json"])
    return sum_file_durations(files, holder.manager.books_root)

def get_book(book_id: str) -> dict[str, Any]:
    from app.services.conflicts import _compute_conflicts

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

def bulk_approve(body: BulkApprove) -> dict[str, Any]:
    from app.services.conflicts import _compute_conflicts

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
