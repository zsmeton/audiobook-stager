from __future__ import annotations

from fastapi import APIRouter

from app.services.books import (
    bind_holder,
    list_books,
    get_book_duration,
    get_book,
    patch_book,
    preview_book_target_key,
    lookup_book,
    approve_book,
    complete_partial_book,
    remove_extras_book,
    bulk_approve,
    skip_book,
    unskip_book,
    bulk_unskip,
    revert_book,
    bulk_revert,
    get_book_decisions,
)

router = APIRouter(prefix="/api")

router.get("/books")(list_books)
router.get("/books/{book_id}/duration")(get_book_duration)
router.get("/books/{book_id}")(get_book)
router.patch("/books/{book_id}")(patch_book)
router.post("/books/{book_id}/target-key-preview")(preview_book_target_key)
router.post("/books/{book_id}/lookup")(lookup_book)
router.post("/books/{book_id}/approve")(approve_book)
router.post("/books/{book_id}/complete-partial")(complete_partial_book)
router.post("/books/{book_id}/remove-extras")(remove_extras_book)
router.post("/books/bulk-approve")(bulk_approve)
router.post("/books/{book_id}/skip")(skip_book)
router.post("/books/{book_id}/unskip")(unskip_book)
router.post("/books/bulk-unskip")(bulk_unskip)
router.post("/books/{book_id}/revert")(revert_book)
router.post("/books/bulk-revert")(bulk_revert)
router.get("/books/{book_id}/decisions")(get_book_decisions)


def bind(state: object) -> None:
    bind_holder(state)
