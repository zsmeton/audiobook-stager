from __future__ import annotations

import os
from pathlib import Path

from stager_core.paths import audiobooks_root, books_root, staging_config_root


def config_root() -> Path:
    return staging_config_root()


def db_path() -> Path:
    root = config_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "stager.db"


def books_path() -> Path:
    return books_root()


def library_path() -> Path:
    return audiobooks_root()
