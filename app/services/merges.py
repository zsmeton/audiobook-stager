from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import unquote

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stager_core.discovery import FlatBook
from stager_core.metadata.duration import sum_file_durations
from stager_core.conflicts import pin_flags_for_operator_fields
from stager_core.staging import resolve_merged_staged_names, stage_merged_books, unstage_book

from app.db import (
    DB_LOCK,
    _utcnow,
    clear_conflict_resolution_for_key,
    delete_book_merges,
    load_merged_members,
    save_book_merge,
)

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

def _compute_merges() -> tuple[list[dict[str, Any]], set[str]]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    with _compute_conflicts_lock:
        session = _ensure_session()
        if holder.conn is not None:
            session.refresh_resolution_groups(holder.conn)
        return session.get_merges()

def list_merges() -> dict[str, Any]:
    groups, merge_ids = _compute_merges()
    return {"groups": groups, "merge_book_ids": sorted(merge_ids)}

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
            author_set, title_set, series_set, series_index_set = pin_flags_for_operator_fields(
                primary_row,
                chosen_author=chosen_author,
                chosen_title=chosen_title,
                chosen_series=chosen_series,
                chosen_series_index=chosen_series_index,
            )
            holder.conn.execute(
                """
                UPDATE books SET
                    chosen_author = ?, chosen_title = ?,
                    chosen_series = ?, chosen_series_index = ?,
                    chosen_author_set = ?, chosen_title_set = ?,
                    chosen_series_set = ?, chosen_series_index_set = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    author,
                    title,
                    series,
                    series_index,
                    author_set,
                    title_set,
                    series_set,
                    series_index_set,
                    now,
                    primary_book_id,
                ),
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


# Last so app.api can re-export this module while it is still loading.
from app.services.books import (
    _compute_conflicts_lock,
    _ensure_session,
    _flatbook_from_row,
    _get_book_row,
    _inode_index_for_stage,
    _renew_lock,
    _resolve_stage_metadata,
)

