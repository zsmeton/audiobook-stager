from __future__ import annotations

from fastapi import APIRouter

from app.services.conflicts import (
    bind_holder,
    list_conflicts,
    get_conflict_duration,
    get_conflict,
    save_conflict_edits,
    approve_conflict,
    preview_conflict_merge,
    approve_conflict_merge,
)

router = APIRouter(prefix="/api")

router.get("/conflicts")(list_conflicts)
router.get("/conflicts/{target_key:path}/duration")(get_conflict_duration)
router.get("/conflicts/{target_key:path}")(get_conflict)
router.post("/conflicts/{target_key:path}/save-edits")(save_conflict_edits)
router.post("/conflicts/{target_key:path}/approve")(approve_conflict)
router.post("/conflicts/{target_key:path}/merge/preview")(preview_conflict_merge)
router.post("/conflicts/{target_key:path}/merge")(approve_conflict_merge)


def bind(state: object) -> None:
    bind_holder(state)
