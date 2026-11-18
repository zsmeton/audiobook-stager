from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from stager_core.fingerprint import FingerprintCache, book_id_from_fingerprints, file_fingerprint
from stager_core.media_kind import AUDIOBOOK, get_kind

AUDIO_EXT = get_kind(AUDIOBOOK).extensions()
INCOMPLETE_SUFFIXES = (".part", ".!qb", ".!qB", ".crdownload", ".tmp")
PART_RE = re.compile(
    r"^(\d{1,3}|part\s*\d+|disc\s*\d+|track\s*\d+)([\.\-_\s]|$)",
    re.IGNORECASE,
)
SUFFIX_PART_RE = re.compile(r"[\-\s_#]+(\d{1,3})$", re.IGNORECASE)
PAREN_PART_RE = re.compile(r"\(\d{1,3}\)$")
PART_IN_STEM_RE = re.compile(r"[\-_]?part\d+$", re.IGNORECASE)
P_SUFFIX_RE = re.compile(r"P\d+$", re.IGNORECASE)
PART_WORD_RE = re.compile(r"\bpart\s*\d+\b", re.IGNORECASE)
BRACKET_PART_RE = re.compile(r"\[\d+(?:-\d+)?\]$")
GENERIC_FOLDER_RE = re.compile(
    r"^(volume\s*\d+|book\s*\d+|disc\s*\d+|cd\s*\d+|part\s*\d+)(\s+audiobooks?)?$",
    re.IGNORECASE,
)
SKIP_NAMES = {
    ".hardlink-test-src",
    ".hardlink-test-dst",
    "audiobook-sample.mp3",
}


def is_incomplete(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(suffix.lower()) for suffix in INCOMPLETE_SUFFIXES)


def is_audio(path: Path) -> bool:
    return get_kind(AUDIOBOOK).matches(path) and not is_incomplete(path)


def looks_like_part(filename: str) -> bool:
    stem = Path(filename).stem.strip()
    if PART_RE.match(stem):
        return True
    if SUFFIX_PART_RE.search(stem):
        return True
    if PAREN_PART_RE.search(stem):
        return True
    if PART_WORD_RE.search(stem):
        return True
    if P_SUFFIX_RE.search(stem):
        return True
    if PART_IN_STEM_RE.search(stem):
        return True
    return bool(BRACKET_PART_RE.search(stem))


def stem_base(stem: str) -> str:
    stem = BRACKET_PART_RE.sub("", stem).strip()
    stem = PAREN_PART_RE.sub("", stem).strip()
    stem = P_SUFFIX_RE.sub("", stem).strip()
    stem = PART_IN_STEM_RE.sub("", stem).strip()
    stem = PART_WORD_RE.sub("", stem).strip()
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    return SUFFIX_PART_RE.sub("", stem).strip()


def files_are_single_book(filenames: list[str]) -> bool:
    if len(filenames) <= 1:
        return True
    if all(looks_like_part(name) for name in filenames):
        return True
    stems = [Path(name).stem for name in filenames]
    bases = {stem_base(s) for s in stems}
    return len(bases) == 1 and bool(next(iter(bases)))


def sanitize_folder_name(name: str, max_len: int = 120) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_len]


def is_generic_folder_name(name: str) -> bool:
    return bool(GENERIC_FOLDER_RE.match(name.strip()))


def enrich_flatten_base(base: str, parts: list[str], filenames: list[str]) -> str:
    if not is_generic_folder_name(base):
        return base

    if filenames and files_are_single_book(filenames):
        derived = sanitize_folder_name(stem_base(Path(filenames[0]).stem))
        if derived and derived != "untitled" and not is_generic_folder_name(derived):
            return derived

    ancestors = [
        sanitize_folder_name(part)
        for part in parts[:-1]
        if part and not is_generic_folder_name(part)
    ]
    if ancestors:
        context = ancestors[-1] if len(ancestors) == 1 else " - ".join(ancestors[-2:])
        return sanitize_folder_name(f"{context} - {base}")
    return base


def disambiguate_name(base: str, context_parts: list[str], used: set[str]) -> str:
    if base not in used:
        return base
    for depth in range(1, len(context_parts) + 1):
        candidate = sanitize_folder_name(" - ".join(context_parts[-depth:] + [base]))
        if candidate not in used:
            return candidate
    digest = hashlib.sha1("/".join(context_parts + [base]).encode()).hexdigest()[:8]
    return sanitize_folder_name(f"{base} ({digest})")


@dataclass
class AudioFile:
    name: str
    source: str
    size_bytes: int


@dataclass
class FlatBook:
    id: str
    flatten_name: str
    source_path: str
    source_path_parts: list[str]
    top_level_pack: str
    parent_context: str
    grouping: str
    files: list[AudioFile] = field(default_factory=list)
    flatten_target: str = ""
    collision: bool = False
    split_from_folder: str | None = None


class DiscoveryCancelled(Exception):
    """Raised when book discovery is aborted via should_cancel."""


def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise DiscoveryCancelled()


def _default_fingerprint_workers() -> int:
    env = os.environ.get("SCAN_FINGERPRINT_WORKERS", "").strip()
    if env.isdigit():
        return max(1, int(env))
    return max(1, min(32, (os.cpu_count() or 4)))


def _walk_audio_by_parent(
    source: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    cancel_check_interval: int = 500,
) -> dict[Path, list[Path]]:
    by_parent: dict[Path, list[Path]] = {}
    walked = 0
    for path in source.rglob("*"):
        walked += 1
        if walked % cancel_check_interval == 0:
            _check_cancel(should_cancel)
        if not is_audio(path):
            continue
        if path.name.lower() in SKIP_NAMES:
            continue
        by_parent.setdefault(path.parent, []).append(path)
    _check_cancel(should_cancel)
    return by_parent


def _fingerprint_one(
    source: Path,
    path: Path,
    fingerprint_cache: FingerprintCache | None,
) -> tuple[Path, str, int, str]:
    st = path.stat()
    rel_file = str(path.relative_to(source)).replace("\\", "/")
    fp = file_fingerprint(
        path,
        stat_result=st,
        cache=fingerprint_cache,
        rel_path=rel_file,
    )
    return path, rel_file, st.st_size, fp


def _fingerprint_files(
    source: Path,
    paths: list[Path],
    *,
    fingerprint_cache: FingerprintCache | None,
    should_cancel: Callable[[], bool] | None,
    workers: int,
) -> dict[Path, tuple[str, int, str]]:
    unique = sorted(set(paths), key=lambda p: str(p).lower())
    if not unique:
        return {}
    if workers <= 1 or len(unique) == 1:
        out: dict[Path, tuple[str, int, str]] = {}
        for path in unique:
            _check_cancel(should_cancel)
            _, rel_file, size_bytes, fp = _fingerprint_one(source, path, fingerprint_cache)
            out[path] = (rel_file, size_bytes, fp)
        return out

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fingerprint_one, source, path, fingerprint_cache): path
            for path in unique
        }
        for future in as_completed(futures):
            _check_cancel(should_cancel)
            path, rel_file, size_bytes, fp = future.result()
            out[path] = (rel_file, size_bytes, fp)
    return out


def discover_books(
    source: Path,
    *,
    on_progress: Callable[[int], None] | None = None,
    progress_interval: int = 10,
    should_cancel: Callable[[], bool] | None = None,
    cancel_check_interval: int = 500,
    fingerprint_cache: FingerprintCache | None = None,
    fingerprint_workers: int | None = None,
) -> list[FlatBook]:
    by_parent = _walk_audio_by_parent(
        source,
        should_cancel=should_cancel,
        cancel_check_interval=cancel_check_interval,
    )

    raw_units: list[tuple[str, Path, list[Path], str | None]] = []
    for parent, files in sorted(by_parent.items(), key=lambda kv: str(kv[0]).lower()):
        rel_parent = parent.relative_to(source)
        names = [f.name for f in files]
        if files_are_single_book(names):
            raw_units.append(("folder", parent, sorted(files), None))
            continue
        for f in sorted(files, key=lambda p: p.name.lower()):
            raw_units.append(("file", f.parent, [f], str(rel_parent)))

    all_files: list[Path] = []
    for _grouping, _parent, files, _split_from in raw_units:
        all_files.extend(files)

    workers = (
        fingerprint_workers
        if fingerprint_workers is not None
        else _default_fingerprint_workers()
    )
    fp_by_path = _fingerprint_files(
        source,
        all_files,
        fingerprint_cache=fingerprint_cache,
        should_cancel=should_cancel,
        workers=workers,
    )

    books: list[FlatBook] = []
    used_names: set[str] = set()

    for grouping, parent, files, split_from in raw_units:
        _check_cancel(should_cancel)
        rel_parent = parent.relative_to(source)
        parts = list(rel_parent.parts)
        top = parts[0] if parts else source.name

        filenames = [f.name for f in files]
        if grouping == "folder":
            flatten_base = enrich_flatten_base(
                sanitize_folder_name(parent.name), parts, filenames
            )
            parent_context = parts[-2] if len(parts) >= 2 else ""
        else:
            flatten_base = enrich_flatten_base(
                sanitize_folder_name(files[0].stem), parts, filenames
            )
            parent_context = parent.name
            split_from = str(rel_parent)

        flatten_name = disambiguate_name(flatten_base, parts, used_names)
        used_names.add(flatten_name)

        file_rows: list[tuple[Path, str, int, str]] = []
        for f in sorted(files, key=lambda p: p.name.lower()):
            rel_file, size_bytes, fp = fp_by_path[f]
            file_rows.append((f, rel_file, size_bytes, fp))

        book_id = book_id_from_fingerprints([fp for _, _, _, fp in file_rows])

        books.append(
            FlatBook(
                id=book_id,
                flatten_name=flatten_base,
                source_path=str(rel_parent).replace("\\", "/"),
                source_path_parts=parts,
                top_level_pack=top,
                parent_context=parent_context,
                grouping=grouping,
                files=[
                    AudioFile(
                        name=f.name,
                        source=rel_file,
                        size_bytes=size_bytes,
                    )
                    for f, rel_file, size_bytes, _ in file_rows
                ],
                flatten_target=flatten_name,
                collision=flatten_name != flatten_base,
                split_from_folder=split_from,
            )
        )
        if on_progress and len(books) % progress_interval == 0:
            on_progress(len(books))

    if on_progress and books:
        on_progress(len(books))

    return books
