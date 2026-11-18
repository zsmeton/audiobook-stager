from __future__ import annotations

from fastapi import APIRouter

from app.services.auto import (
    bind_holder,
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

router = APIRouter(prefix="/api")

router.get("/auto/settings")(get_auto_settings_route)
router.patch("/auto/settings")(patch_auto_settings)
router.get("/auto/running")(get_auto_running)
router.post("/auto/run")(start_auto_run)
router.post("/auto/{run_id}/cancel")(cancel_auto_run)
router.post("/auto/cache/clear")(clear_metadata_cache)
router.get("/auto/review")(get_auto_review)
router.post("/auto/review/dismiss")(dismiss_auto_review)
router.get("/auto/feedback")(get_auto_feedback)


def bind(state: object) -> None:
    bind_holder(state)
