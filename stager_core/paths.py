"""Filesystem roots.

``app.settings`` owns path defaults and registers them here on import.
These functions delegate to that registration. This module does not import
``app`` (``stager_core`` may import ``app`` only from ``library_cache``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

_books_root: Callable[[], Path] | None = None
_audiobooks_root: Callable[[], Path] | None = None
_staging_config_root: Callable[[], Path] | None = None


def bind_path_resolvers(
    *,
    books: Callable[[], Path],
    audiobooks: Callable[[], Path],
    config: Callable[[], Path],
) -> None:
    """Register the resolvers owned by ``app.settings``."""
    global _books_root, _audiobooks_root, _staging_config_root
    _books_root = books
    _audiobooks_root = audiobooks
    _staging_config_root = config


def _resolved(resolver: Callable[[], Path] | None) -> Path:
    if resolver is None:
        raise RuntimeError(
            "path defaults are resolved in app.settings; import app.settings first"
        )
    return resolver()


def books_root() -> Path:
    return _resolved(_books_root)


def audiobooks_root() -> Path:
    return _resolved(_audiobooks_root)


def staging_config_root() -> Path:
    return _resolved(_staging_config_root)
