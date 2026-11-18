"""Process-local library and inode indexes.

The in-memory inode index is the single-writer cache for filesystem mutations
in this process. A second process must not write the same library. This module
does not import the app. The app may register the live session so a ready
session's indexes are reused instead of walking the library again.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_cache: dict[str, tuple[Any, dict[int, list[str]]]] = {}
_session_provider: Callable[[], Any] | None = None


def bind_session_provider(provider: Callable[[], Any] | None) -> None:
    """Register the live session. Callers in the app pass it in."""
    global _session_provider
    _session_provider = provider


def _cache_key(library_root: Path) -> str:
    return str(library_root.resolve())


def _live_session() -> Any:
    if _session_provider is None:
        return None
    return _session_provider()


def _ready_session(library_root: Path) -> Any:
    session = _live_session()
    if session is not None and session.session_ready:
        if str(session.library_root.resolve()) == _cache_key(library_root):
            return session
    return None


def get_library_indexes(library_root: Path) -> tuple[Any, dict[int, list[str]]]:
    session = _ready_session(library_root)
    if session is not None:
        return session.library_index, session.inode_index

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
    session = _ready_session(library_root)
    if session is not None:
        return session.get_inode_index_copy()
    _, inode_index = get_library_indexes(library_root)
    return {ino: list(paths) for ino, paths in inode_index.items()}


def invalidate_library_cache(library_root: Path | None = None) -> None:
    session = _live_session()
    if session is not None:
        session.session_ready = False
        session.stale = True
    with _lock:
        if library_root is None:
            _cache.clear()
        else:
            _cache.pop(_cache_key(library_root), None)
