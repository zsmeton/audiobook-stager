from __future__ import annotations

from fastapi import APIRouter

from app.services.health import (
    bind_holder,
    health,
)

router = APIRouter(prefix="/api")

router.get("/health")(health)


def bind(state: object) -> None:
    bind_holder(state)
