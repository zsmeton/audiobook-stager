from __future__ import annotations

from fastapi import APIRouter

from app.services.scan import (
    bind_holder,
    running_scan,
    latest_scan,
    get_scan,
    cancel_scan,
    start_scan,
)

router = APIRouter(prefix="/api")

router.get("/scan/running")(running_scan)
router.get("/scan/latest")(latest_scan)
router.get("/scan/{scan_id}")(get_scan)
router.post("/scan/{scan_id}/cancel")(cancel_scan)
router.post("/scan")(start_scan)


def bind(state: object) -> None:
    bind_holder(state)
