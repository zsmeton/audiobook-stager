from __future__ import annotations

import os
from pathlib import Path


def resolve_seed_source_path(books_root: Path, source_path: str) -> str:
    rel = str(source_path or "").strip()
    if not rel:
        return str(books_root.resolve())
    return str((books_root / rel.replace("/", os.sep)).resolve())


def resolve_library_target_path(library_root: Path, target_key: str) -> str:
    key = str(target_key or "").strip()
    if "/" not in key:
        return ""
    author_dir, title_dir = key.split("/", 1)
    return str((library_root / author_dir / title_dir).resolve())
