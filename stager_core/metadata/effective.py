from __future__ import annotations

import json
from typing import Any

from stager_core.staging import compute_target_key


def _row_get(row: dict[str, Any] | Any, key: str, default: object = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _is_set(row: dict[str, Any] | Any, key: str) -> bool:
    return bool(int(_row_get(row, key, 0) or 0))


def primary_candidate_series_from_candidates(candidates: list[Any]) -> tuple[str, str]:
    """Series fields from the primary (suggested) candidate row."""
    if not candidates:
        return "", ""
    primary: Any | None = None
    for cand in candidates:
        if isinstance(cand, dict):
            in_win = bool(cand.get("in_winning_cluster"))
            rank = int(cand.get("medoid_rank") or 999)
        else:
            in_win = bool(getattr(cand, "in_winning_cluster", False))
            rank = int(getattr(cand, "medoid_rank", None) or 999)
        if in_win and rank == 1:
            primary = cand
            break
    if primary is None:
        primary = candidates[0]
    if isinstance(primary, dict):
        return (
            str(primary.get("series") or "").strip(),
            str(primary.get("series_index") or "").strip(),
        )
    return (
        str(getattr(primary, "series", "") or "").strip(),
        str(getattr(primary, "series_index", "") or "").strip(),
    )


def _primary_candidate_series_from_row(row: dict[str, Any] | Any) -> tuple[str, str]:
    raw = _row_get(row, "candidates_json", "[]")
    if isinstance(raw, list):
        return primary_candidate_series_from_candidates(raw)
    if not isinstance(raw, str) or not str(raw).strip():
        return "", ""
    try:
        candidates = json.loads(raw)
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(candidates, list):
        return "", ""
    return primary_candidate_series_from_candidates(candidates)


def _suggested_series_values(row: dict[str, Any] | Any) -> tuple[str, str]:
    series = (_row_get(row, "suggested_series") or "").strip()
    series_index = (_row_get(row, "suggested_series_index") or "").strip()
    if series or series_index:
        return series, series_index
    return _primary_candidate_series_from_row(row)


def effective_author(row: dict[str, Any] | Any) -> str:
    if _is_set(row, "chosen_author_set"):
        return (_row_get(row, "chosen_author") or "").strip() or "Unknown Author"
    return (_row_get(row, "suggested_author") or "").strip() or "Unknown Author"


def effective_title(row: dict[str, Any] | Any, *, flatten_name: str = "") -> str:
    if _is_set(row, "chosen_title_set"):
        title = (_row_get(row, "chosen_title") or "").strip()
        return title or flatten_name or "Untitled"
    title = (_row_get(row, "suggested_title") or "").strip()
    return title or flatten_name or "Untitled"


def effective_series(row: dict[str, Any] | Any) -> str:
    if _is_set(row, "chosen_series_set"):
        return (_row_get(row, "chosen_series") or "").strip()
    series, _ = _suggested_series_values(row)
    return series


def effective_series_index(row: dict[str, Any] | Any) -> str:
    if _is_set(row, "chosen_series_index_set"):
        return (_row_get(row, "chosen_series_index") or "").strip()
    _, series_index = _suggested_series_values(row)
    return series_index


def chosen_series_state(row: dict[str, Any] | Any) -> str | None:
    """Operator series intent when pinned; None = follow suggestion."""
    if not _is_set(row, "chosen_series_set"):
        return None
    if not (_row_get(row, "chosen_series") or "").strip():
        return "confirmed_none"
    return "confirmed"


def effective_series_state(row: dict[str, Any] | Any) -> str:
    cs = chosen_series_state(row)
    if cs is not None:
        return cs
    state = (_row_get(row, "suggested_series_state") or "unknown").strip() or "unknown"
    series, series_index = _suggested_series_values(row)
    if state == "confirmed_none" and (series or series_index):
        return "confirmed"
    return state


def any_chosen_set(row: dict[str, Any] | Any) -> bool:
    return any(
        _is_set(row, key)
        for key in (
            "chosen_author_set",
            "chosen_title_set",
            "chosen_series_set",
            "chosen_series_index_set",
        )
    )


def effective_metadata(row: dict[str, Any] | Any) -> dict[str, str]:
    flatten = _row_get(row, "flatten_name") or ""
    return {
        "effective_author": effective_author(row),
        "effective_title": effective_title(row, flatten_name=flatten),
        "effective_series": effective_series(row),
        "effective_series_index": effective_series_index(row),
        "effective_series_state": effective_series_state(row),
    }


def target_key_preview(row: dict[str, Any] | Any) -> str:
    eff = effective_metadata(row)
    author = eff["effective_author"]
    title = eff["effective_title"]
    series = eff["effective_series"]
    series_index = eff["effective_series_index"]
    state = eff["effective_series_state"]

    if state == "confirmed_none":
        return compute_target_key(author, title)

    if state == "unknown":
        if series:
            return compute_target_key(author, title, series, series_index)
        return compute_target_key(author, title)

    if series:
        return compute_target_key(author, title, series, series_index)
    return compute_target_key(author, title)
