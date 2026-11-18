from __future__ import annotations

from typing import Any


def resolve_author_title(book: dict[str, Any]) -> tuple[str, str]:
    if int(book.get("chosen_author_set") or 0):
        author = (book.get("chosen_author") or "").strip()
    else:
        author = (book.get("suggested_author") or "").strip()
    if int(book.get("chosen_title_set") or 0):
        title = (book.get("chosen_title") or "").strip()
    else:
        title = (book.get("suggested_title") or "").strip()
    return author, title


def is_eligible_for_auto_stage(
    book: dict[str, Any],
    conflict_ids: set[str],
    min_confidence: float,
) -> bool:
    if book.get("status") != "pending":
        return False
    if book.get("id") in conflict_ids:
        return False
    if any(int(book.get(k) or 0) for k in (
        "chosen_author_set",
        "chosen_title_set",
        "chosen_series_set",
        "chosen_series_index_set",
    )):
        return False
    if float(book.get("confidence") or 0) < min_confidence:
        return False
    author, title = resolve_author_title(book)
    return bool(author and title)
