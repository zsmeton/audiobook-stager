from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stager_core.discovery import AUDIO_EXT, _check_cancel
from stager_core.metadata.effective import (
    effective_author,
    effective_metadata,
    effective_title,
    target_key_preview,
)
from stager_core.metadata.paths import (
    resolve_library_target_path,
    resolve_seed_source_path,
)
from stager_core.metadata.tags import read_tags
from stager_core.metadata.types import TagInfo
from stager_core.staging import compute_target_key, source_inode

LIBRARY_SIDE_ID = "library"

FORMAT_RANK = {
    ".m4b": 100,
    ".mp3": 90,
    ".flac": 80,
    ".m4a": 70,
    ".aac": 65,
    ".ogg": 60,
    ".opus": 55,
    ".wav": 50,
    ".wma": 40,
    ".mp4": 35,
}


from stager_core.staging import compute_target_key, source_inode


def effective_author_title(
    chosen_author: str,
    chosen_title: str,
    suggested_author: str,
    suggested_title: str,
    flatten_name: str,
    *,
    chosen_author_set: int = 0,
    chosen_title_set: int = 0,
) -> tuple[str, str]:
    row = {
        "chosen_author": chosen_author,
        "chosen_title": chosen_title,
        "suggested_author": suggested_author,
        "suggested_title": suggested_title,
        "flatten_name": flatten_name,
        "chosen_author_set": chosen_author_set,
        "chosen_title_set": chosen_title_set,
    }
    return effective_author(row), effective_title(row, flatten_name=flatten_name)


def resolve_winner_metadata(
    *,
    chosen_author: str,
    chosen_title: str,
    suggested_author: str,
    suggested_title: str,
    flatten_name: str,
    chosen_author_set: int = 0,
    chosen_title_set: int = 0,
    chosen_series: str = "",
    chosen_series_index: str = "",
    chosen_series_set: int = 0,
    chosen_series_index_set: int = 0,
    suggested_series: str = "",
    suggested_series_index: str = "",
    suggested_series_state: str = "unknown",
    override_author: str | None = None,
    override_title: str | None = None,
    override_series: str | None = None,
    override_series_index: str | None = None,
) -> tuple[str, str, str, str]:
    row = {
        "chosen_author": chosen_author,
        "chosen_title": chosen_title,
        "suggested_author": suggested_author,
        "suggested_title": suggested_title,
        "flatten_name": flatten_name,
        "chosen_author_set": chosen_author_set,
        "chosen_title_set": chosen_title_set,
        "chosen_series": chosen_series,
        "chosen_series_index": chosen_series_index,
        "chosen_series_set": chosen_series_set,
        "chosen_series_index_set": chosen_series_index_set,
        "suggested_series": suggested_series,
        "suggested_series_index": suggested_series_index,
        "suggested_series_state": suggested_series_state,
    }
    if override_author is not None:
        author = override_author.strip() or "Unknown Author"
    else:
        author = effective_author(row)
    if override_title is not None:
        title = override_title.strip() or flatten_name or "Untitled"
    else:
        title = effective_title(row, flatten_name=flatten_name)
    if override_series is not None:
        series = override_series.strip()
    else:
        from stager_core.metadata.effective import effective_series

        series = effective_series(row)
    if override_series_index is not None:
        series_index = override_series_index.strip()
    else:
        from stager_core.metadata.effective import effective_series_index

        series_index = effective_series_index(row)
    return author, title, series, series_index


def book_target_key(row: dict[str, Any]) -> str:
    return target_key_preview(row)


def _format_rank(suffix: str) -> int:
    return FORMAT_RANK.get(suffix.lower(), 0)


def _dominant_format(suffixes: list[str]) -> str:
    if not suffixes:
        return ""
    return max(suffixes, key=lambda s: (_format_rank(s), s))


def _side_score(
    *,
    file_count: int,
    total_size_bytes: int,
    dominant_format: str,
    confidence: float,
) -> tuple[int, int, float, int]:
    fmt_score = _format_rank(dominant_format)
    single_bonus = 10 if file_count == 1 and dominant_format.lower() == ".m4b" else 0
    return (fmt_score + single_bonus, -total_size_bytes, confidence, -file_count)


def summarize_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    suffixes = [Path(f.get("name", "")).suffix.lower() for f in files if f.get("name")]
    total_size = sum(int(f.get("size_bytes") or 0) for f in files)
    dominant = _dominant_format(suffixes)
    return {
        "file_count": len(files),
        "total_size_bytes": total_size,
        "dominant_format": dominant,
        "format_rank": _format_rank(dominant),
    }


def tags_summary_dict(tags: dict[str, Any]) -> dict[str, str]:
    return {
        "author": tags.get("artist") or tags.get("albumartist") or "",
        "title": tags.get("title") or tags.get("album") or "",
        "narrator": tags.get("narrator") or "",
        "asin": tags.get("asin") or "",
    }


def _taginfo_to_dict(tags: TagInfo) -> dict[str, Any]:
    return {
        "title": tags.title,
        "album": tags.album,
        "artist": tags.artist,
        "albumartist": tags.albumartist,
        "asin": tags.asin,
        "narrator": tags.narrator,
    }


@dataclass
class LibrarySide:
    target_key: str
    files: list[dict[str, Any]] = field(default_factory=list)
    tags: TagInfo = field(default_factory=TagInfo)

    def to_summary(self) -> dict[str, Any]:
        summary = summarize_files(self.files)
        summary["confidence"] = 1.0
        summary["tags_summary"] = tags_summary_dict(_taginfo_to_dict(self.tags))
        return summary


def build_library_index(
    library_root: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    cancel_check_interval: int = 500,
    on_progress: Callable[[int], None] | None = None,
    progress_interval: int = 50,
    workers: int | None = None,
) -> dict[str, LibrarySide]:
    from stager_core.target_index import build_target_indexes

    library_index, _ = build_target_indexes(
        library_root,
        should_cancel=should_cancel,
        cancel_check_interval=cancel_check_interval,
        on_progress=on_progress,
        progress_interval=progress_interval,
        workers=workers,
    )
    return library_index


def _seed_conflicts_with_library(
    book_files: list[dict[str, Any]],
    source_root: Path,
    library_root: Path,
    library_side: LibrarySide,
    inode_index: dict[int, list[str]],
) -> bool:
    if not library_side.files:
        return False

    all_linked = True
    for af in book_files:
        src = source_root / str(af["source"]).replace("/", os.sep)
        ino = source_inode(src)
        if ino is None or ino not in inode_index:
            all_linked = False
            break

    if all_linked:
        return False

    for lf in library_side.files:
        lib_path = library_root / str(lf["relative_path"]).replace("/", os.sep)
        if lib_path.is_file():
            return True
    return False


def book_row_target_key(row: dict[str, Any]) -> str:
    return book_target_key(row)


def _seed_side_from_row(row: dict[str, Any], source_root: Path) -> dict[str, Any]:
    files = row.get("files") or []
    summary = summarize_files(files)
    tags = row.get("tags") or {}
    source_path = row.get("source_path") or ""
    return {
        "side_id": row["id"],
        "type": "seed",
        "book_id": row["id"],
        "source_path": source_path,
        "full_path": resolve_seed_source_path(source_root, source_path),
        "confidence": float(row.get("confidence") or 0),
        "candidates": row.get("candidates") or [],
        "chosen_author": row.get("chosen_author") or "",
        "chosen_title": row.get("chosen_title") or "",
        "suggested_author": row.get("suggested_author") or "",
        "suggested_title": row.get("suggested_title") or "",
        "effective_author": row.get("effective_author") or "",
        "effective_title": row.get("effective_title") or "",
        "effective_series": row.get("effective_series") or "",
        "effective_series_index": row.get("effective_series_index") or "",
        "tags": tags,
        "files": files,
        "tags_summary": tags_summary_dict(tags),
        **summary,
    }


def _score_side(side: dict[str, Any]) -> tuple[int, int, float, int]:
    return _side_score(
        file_count=int(side.get("file_count") or 0),
        total_size_bytes=int(side.get("total_size_bytes") or 0),
        dominant_format=str(side.get("dominant_format") or ""),
        confidence=float(side.get("confidence") or 0),
    )


def pick_default_winner(sides: list[dict[str, Any]]) -> str:
    if not sides:
        return ""
    for side in sides:
        if side.get("type") == "library":
            return str(side["side_id"])
    best = max(sides, key=_score_side)
    return str(best["side_id"])


def classify_conflict_kind(*, has_library: bool, seed_count: int) -> str:
    if has_library and seed_count >= 2:
        return "mixed"
    if has_library:
        return "staged"
    return "pending"


def _side_exists(sides: list[dict[str, Any]], side_id: str) -> bool:
    if not side_id:
        return False
    return any(s["side_id"] == side_id for s in sides)


def detect_conflict_groups(
    book_rows: list[dict[str, Any]],
    library_root: Path,
    source_root: Path,
    persisted: dict[str, str],
    library_index: dict[str, LibrarySide],
    inode_index: dict[int, list[str]],
) -> tuple[list[dict[str, Any]], set[str]]:

    eligible: list[dict[str, Any]] = []
    for row in book_rows:
        status = row.get("status") or ""
        if status in {"staged", "skipped", "partial_staged", "merged"}:
            continue
        eligible.append(row)

    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        key = book_row_target_key(row)
        by_key.setdefault(key, []).append(row)

    conflict_book_ids: set[str] = set()
    groups: list[dict[str, Any]] = []

    for target_key, rows in sorted(by_key.items()):
        library_side = library_index.get(target_key)
        has_library = False
        if library_side and library_side.files:
            for row in rows:
                files = row.get("files") or []
                if _seed_conflicts_with_library(
                    files, source_root, library_root, library_side, inode_index
                ):
                    has_library = True
                    break

        if len(rows) < 2 and not has_library:
            continue

        sides: list[dict[str, Any]] = []
        for row in rows:
            sides.append(_seed_side_from_row(row, source_root))
            conflict_book_ids.add(row["id"])

        if has_library and library_side:
            lib_summary = library_side.to_summary()
            sides.append(
                {
                    "side_id": LIBRARY_SIDE_ID,
                    "type": "library",
                    "source_path": target_key,
                    "full_path": resolve_library_target_path(library_root, target_key),
                    "tags": _taginfo_to_dict(library_side.tags),
                    **lib_summary,
                }
            )

        if len(sides) < 2:
            for row in rows:
                conflict_book_ids.discard(row["id"])
            continue

        computed_winner = pick_default_winner(sides)
        persisted_winner = persisted.get(target_key, "")
        winner_side_id = (
            persisted_winner if _side_exists(sides, persisted_winner) else computed_winner
        )

        author_dir, title_dir = target_key.split("/", 1)
        seed_ids = [row["id"] for row in rows]
        groups.append(
            {
                "target_key": target_key,
                "target_author": author_dir,
                "target_title": title_dir,
                "sides": sides,
                "default_winner_side_id": computed_winner,
                "computed_winner_side_id": computed_winner,
                "persisted_winner_side_id": persisted_winner or None,
                "winner_side_id": winner_side_id,
                "has_library_side": has_library,
                "conflict_kind": classify_conflict_kind(
                    has_library=has_library, seed_count=len(rows)
                ),
                "merge_eligible_seed_ids": seed_ids if len(seed_ids) >= 2 else [],
            }
        )

    return groups, conflict_book_ids
