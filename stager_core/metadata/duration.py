from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from stager_core.discovery import AUDIO_EXT


def read_duration_seconds(path: Path) -> float:
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return 0.0

    if not path.is_file():
        return 0.0

    try:
        audio = MutagenFile(path)
    except Exception:
        return 0.0
    if audio is None or audio.info is None:
        return 0.0

    length = getattr(audio.info, "length", None)
    if length is None:
        return 0.0
    try:
        return max(0.0, float(length))
    except (TypeError, ValueError):
        return 0.0


def sum_file_durations(
    files: list[dict[str, Any]],
    root: Path,
    *,
    source_key: str = "source",
) -> dict[str, Any]:
    total = 0
    out_files: list[dict[str, Any]] = []
    for entry in files:
        rel = str(entry.get(source_key) or "")
        name = str(entry.get("name") or Path(rel).name or "")
        path = root / rel.replace("/", os.sep)
        seconds = int(read_duration_seconds(path))
        out_files.append({"name": name, "duration_seconds": seconds})
        total += seconds
    return {"total_duration_seconds": total, "files": out_files}


def sum_library_target_durations(library_root: Path, target_key: str) -> dict[str, Any]:
    if "/" not in target_key:
        return {"total_duration_seconds": 0, "files": []}

    author_dir, title_dir = target_key.split("/", 1)
    target_dir = library_root / author_dir / title_dir
    if not target_dir.is_dir():
        return {"total_duration_seconds": 0, "files": []}

    total = 0
    out_files: list[dict[str, Any]] = []
    for path in sorted(target_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXT:
            continue
        seconds = int(read_duration_seconds(path))
        out_files.append({"name": path.name, "duration_seconds": seconds})
        total += seconds
    return {"total_duration_seconds": total, "files": out_files}
