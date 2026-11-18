from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stager_core.conflicts import LIBRARY_SIDE_ID, pin_flags_for_operator_fields
from stager_core.metadata.duration import sum_file_durations, sum_library_target_durations
from stager_core.staging import compute_target_key, replace_library_target, stage_book_author_title

from app.db import DB_LOCK, _utcnow, save_conflict_resolution

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

def _compute_conflicts() -> tuple[list[dict[str, Any]], set[str]]:
    if holder.conn is None or holder.manager is None:
        raise HTTPException(500, "not initialized")
    with _compute_conflicts_lock:
        session = _ensure_session()
        if holder.conn is not None:
            session.refresh_resolution_groups(holder.conn)
        return session.get_conflicts()

def list_conflicts() -> dict[str, Any]:
    groups, conflict_ids = _compute_conflicts()
    return {"groups": groups, "conflict_book_ids": sorted(conflict_ids)}

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

def get_conflict(target_key: str) -> dict[str, Any]:
    key = unquote(target_key)
    groups, _ = _compute_conflicts()
    for group in groups:
        if group["target_key"] == key:
            return group
    raise HTTPException(404, "conflict group not found")

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
                """
                SELECT id, status,
                       suggested_series, suggested_series_index,
                       chosen_author_set, chosen_title_set,
                       chosen_series_set, chosen_series_index_set
                FROM books WHERE id = ?
                """,
                (edit.book_id,),
            ).fetchone()
            if not row:
                errors.append({"book_id": edit.book_id, "error": "book not found"})
                continue
            if row["status"] != "pending":
                errors.append({"book_id": edit.book_id, "error": "book not editable"})
                continue
            author_set, title_set, series_set, series_index_set = pin_flags_for_operator_fields(
                row,
                chosen_author=edit.chosen_author,
                chosen_title=edit.chosen_title,
                chosen_series=edit.chosen_series,
                chosen_series_index=edit.chosen_series_index,
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
                    edit.chosen_author,
                    edit.chosen_title,
                    edit.chosen_series,
                    edit.chosen_series_index,
                    author_set,
                    title_set,
                    series_set,
                    series_index_set,
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
        author_set, title_set, series_set, series_index_set = pin_flags_for_operator_fields(
            row,
            chosen_author=body.chosen_author,
            chosen_title=body.chosen_title,
            chosen_series=body.chosen_series,
            chosen_series_index=body.chosen_series_index,
        )
        with DB_LOCK:
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
                    _utcnow(),
                    winner,
                ),
            )
            holder.conn.commit()
    staging_key = compute_target_key(author, title, series, series_index)
    if group.get("has_library_side") and staging_key == key:
        replace_result = replace_library_target(
            holder.manager.library_root,
            author,
            title,
            series,
            series_index,
        )
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
from app.services.merges import (
    MergeApprove,
    MergePreviewBody,
    _merge_preview_payload,
    _perform_merge,
    _pick_merge_primary,
)

