from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stager_core.metadata.cleanup_pipeline import validate_step_ids
from stager_core.metadata.effective import effective_metadata, target_key_preview
from stager_core.metadata.title_extraction import ADVANCED_DEFAULT_POST, ADVANCED_DEFAULT_PRE

from app.activity_lock import get_activity_lock
from app.auto import AutoRunAlreadyRunning, AutoRunBlocked
from app.db import (
    DB_LOCK,
    _utcnow,
    get_auto_settings,
    get_last_auto_run,
    record_auto_change_feedback,
    row_to_feedback,
    update_auto_settings,
)
from app.scheduler import reschedule_auto_job

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

class AutoDismissBody(BaseModel):
    action_ids: list[str] = Field(default_factory=list)
    dismiss_all: bool = False

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

def get_auto_running() -> dict[str, Any]:
    if holder.auto_manager is None:
        raise HTTPException(500, "auto manager not initialized")
    row = holder.auto_manager.get_running_run()
    if not row or not holder.auto_manager.is_running():
        return {"status": "none"}
    return dict(row)

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

def cancel_auto_run(run_id: str) -> dict[str, Any]:
    if holder.auto_manager is None:
        raise HTTPException(500, "auto manager not initialized")
    if not holder.auto_manager.cancel_run(run_id):
        raise HTTPException(409, "auto-run is not active")
    return {"cancelled": True, "run_id": run_id}

def clear_metadata_cache() -> dict[str, Any]:
    if holder.conn is None:
        raise HTTPException(500, "database not initialized")
    with DB_LOCK:
        holder.conn.execute("DELETE FROM api_cache")
        update_auto_settings(holder.conn, cache_relookup_pending=True)
        holder.conn.commit()
    _renew_lock("cache_clear")
    return {"status": "cleared", "cache_relookup_pending": True}

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


# Last so app.api can re-export this module while it is still loading.
from app.services.books import _renew_lock

