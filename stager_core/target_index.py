from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from stager_core.conflicts import LibrarySide
from stager_core.discovery import AUDIO_EXT, _check_cancel
from stager_core.metadata.tags import read_tags
from stager_core.metadata.types import TagInfo
from stager_core.staging import source_inode


def _default_workers() -> int:
    return max(1, min(32, (os.cpu_count() or 4)))


@dataclass(frozen=True)
class _LibraryFileRow:
    rel: str
    target_key: str
    name: str
    size_bytes: int
    format: str
    inode: int | None


def _target_key_for_rel(parts: tuple[str, ...]) -> str | None:
    if len(parts) < 2:
        return None
    if len(parts) == 3:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) >= 4:
        return "/".join(parts[:3])
    return f"{parts[0]}/{parts[1]}"


def _index_one_file(library_root: Path, path: Path) -> _LibraryFileRow | None:
    if path.suffix.lower() not in AUDIO_EXT:
        return None
    try:
        rel_path = path.relative_to(library_root)
    except ValueError:
        return None
    parts = rel_path.parts
    target_key = _target_key_for_rel(parts)
    if target_key is None:
        return None
    rel = str(rel_path).replace("\\", "/")
    st = path.stat()
    return _LibraryFileRow(
        rel=rel,
        target_key=target_key,
        name=path.name,
        size_bytes=st.st_size,
        format=path.suffix.lower(),
        inode=source_inode(path),
    )


def _read_side_tags(library_root: Path, side: LibrarySide) -> None:
    if not side.files:
        return
    merged = TagInfo()
    for lf in side.files[:5]:
        info = read_tags(library_root / lf["relative_path"])
        if not merged.title and info.title:
            merged.title = info.title
        if not merged.album and info.album:
            merged.album = info.album
        if not merged.artist and info.artist:
            merged.artist = info.artist
        if not merged.albumartist and info.albumartist:
            merged.albumartist = info.albumartist
        if not merged.asin and info.asin:
            merged.asin = info.asin
        if not merged.narrator and info.narrator:
            merged.narrator = info.narrator
    side.tags = merged


def build_target_indexes(
    library_root: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    cancel_check_interval: int = 500,
    on_progress: Callable[[int], None] | None = None,
    progress_interval: int = 50,
    workers: int | None = None,
) -> tuple[dict[str, LibrarySide], dict[int, list[str]]]:
    library_index: dict[str, LibrarySide] = {}
    inode_index: dict[int, list[str]] = {}
    if not library_root.is_dir():
        return library_index, inode_index

    audio_paths: list[Path] = []
    walked = 0
    for path in library_root.rglob("*"):
        walked += 1
        if walked % cancel_check_interval == 0:
            _check_cancel(should_cancel)
        if path.is_file() and path.suffix.lower() in AUDIO_EXT:
            audio_paths.append(path)

    _check_cancel(should_cancel)
    if not audio_paths:
        return library_index, inode_index

    worker_count = workers if workers is not None else _default_workers()
    rows: list[_LibraryFileRow] = []
    indexed = 0

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(_index_one_file, library_root, path): path for path in audio_paths
        }
        for future in as_completed(futures):
            _check_cancel(should_cancel)
            row = future.result()
            if row is None:
                continue
            rows.append(row)
            indexed += 1
            if on_progress and indexed % progress_interval == 0:
                on_progress(indexed)

    _check_cancel(should_cancel)

    for row in sorted(rows, key=lambda r: r.rel.lower()):
        side = library_index.setdefault(row.target_key, LibrarySide(target_key=row.target_key))
        side.files.append(
            {
                "name": row.name,
                "relative_path": row.rel,
                "size_bytes": row.size_bytes,
                "format": row.format,
            }
        )
        if row.inode is not None:
            inode_index.setdefault(row.inode, []).append(row.rel)

    if on_progress and indexed:
        on_progress(indexed)

    sides = [side for side in library_index.values() if side.files]
    if sides:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [pool.submit(_read_side_tags, library_root, side) for side in sides]
            for future in as_completed(futures):
                _check_cancel(should_cancel)
                future.result()

    _check_cancel(should_cancel)
    return library_index, inode_index
