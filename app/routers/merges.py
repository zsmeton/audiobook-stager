from __future__ import annotations

from fastapi import APIRouter

from app.services.merges import (
    bind_holder,
    list_merges,
    get_merge,
    preview_merge,
    approve_merge,
    unmerge_books,
)

router = APIRouter(prefix="/api")

router.get("/merges")(list_merges)
router.get("/merges/{target_key:path}")(get_merge)
router.post("/merges/{target_key:path}/preview")(preview_merge)
router.post("/merges/{target_key:path}")(approve_merge)
router.delete("/merges/{primary_book_id}")(unmerge_books)


def bind(state: object) -> None:
    bind_holder(state)
