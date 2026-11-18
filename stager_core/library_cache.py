from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_cache: dict[str, tuple[Any, dict[int, list[str]]]] = {}


def _cache_key(library_root: Path) -> str:
    return str(library_root.resolve())


def _session_indexes(library_root: Path) -> tuple[Any, dict[int, list[str]]] | None:
    try:
        from app.api import holder

        session = holder.session
        if session is not None and session.session_ready:
            if str(session.library_root.resolve()) == _cache_key(library_root):
                return session.library_index, session.inode_index
    except ImportError:
        pass
    return None


def get_library_indexes(library_root: Path) -> tuple[Any, dict[int, list[str]]]:
    session_cached = _session_indexes(library_root)
    if session_cached is not None:
        return session_cached

    key = _cache_key(library_root)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    from stager_core.conflicts import build_library_index
    from stager_core.staging import build_inode_index

    library_index = build_library_index(library_root)
    inode_index = build_inode_index(library_root)

    with _lock:
        existing = _cache.get(key)
        if existing is not None:
            return existing
        _cache[key] = (library_index, inode_index)
        return library_index, inode_index


def get_inode_index_copy(library_root: Path) -> dict[int, list[str]]:
    try:
        from app.api import holder

        session = holder.session
        if session is not None and session.session_ready:
            if str(session.library_root.resolve()) == _cache_key(library_root):
                return session.get_inode_index_copy()
    except ImportError:
        pass
    _, inode_index = get_library_indexes(library_root)
    return {ino: list(paths) for ino, paths in inode_index.items()}


def invalidate_library_cache(library_root: Path | None = None) -> None:
    try:
        from app.api import holder

        if holder.session is not None:
            holder.session.session_ready = False
            holder.session.stale = True
    except ImportError:
        pass
    with _lock:
        if library_root is None:
            _cache.clear()
        else:
            _cache.pop(_cache_key(library_root), None)
