from __future__ import annotations

from pathlib import Path
from typing import Any

from stager_core.conflicts import (
    _seed_conflicts_with_library,
    _seed_side_from_row,
    book_row_target_key,
)


def detect_merge_groups(
    book_rows: list[dict[str, Any]],
    library_root: Path,
    source_root: Path,
    library_index: dict[str, Any],
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

    merge_book_ids: set[str] = set()
    groups: list[dict[str, Any]] = []

    for target_key, rows in sorted(by_key.items()):
        if len(rows) < 2:
            continue

        library_side = library_index.get(target_key)
        has_library_conflict = False
        if library_side and library_side.files:
            for row in rows:
                files = row.get("files") or []
                if _seed_conflicts_with_library(
                    files, source_root, library_root, library_side, inode_index
                ):
                    has_library_conflict = True
                    break

        if has_library_conflict:
            continue

        members: list[dict[str, Any]] = []
        for row in rows:
            members.append(_seed_side_from_row(row, source_root))
            merge_book_ids.add(row["id"])

        author_dir, title_dir = target_key.split("/", 1)
        groups.append(
            {
                "target_key": target_key,
                "target_author": author_dir,
                "target_title": title_dir,
                "members": members,
                "member_book_ids": [row["id"] for row in rows],
            }
        )

    return groups, merge_book_ids
