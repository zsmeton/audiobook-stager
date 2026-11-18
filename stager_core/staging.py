from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from stager_core.discovery import (
    AUDIO_EXT,
    FlatBook,
    _check_cancel,
    sanitize_folder_name,
)


def same_inode(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_ino == b.stat().st_ino
    except OSError:
        return False


def source_inode(path: Path) -> int | None:
    try:
        return path.stat().st_ino
    except OSError:
        return None


@dataclass
class BookResult:
    book_id: str
    author: str
    title: str
    source_path: str
    target_path: str
    status: str
    files_linked: int = 0
    files_skipped: int = 0
    duration_ms: int = 0
    error: str | None = None


@dataclass
class StagingFileStatus:
    name: str
    source: str
    size_bytes: int
    status: str
    library_paths: list[str] = field(default_factory=list)


@dataclass
class ExtraLibraryFile:
    name: str
    relative_path: str
    size_bytes: int


@dataclass
class StagingAnalysis:
    linked_count: int
    unlinked_count: int
    source_missing_count: int
    total: int
    target_dir_rel: str
    detail: str
    linked_paths: list[str]
    files: list[StagingFileStatus]
    extra_library_files: list[ExtraLibraryFile]

    def to_dict(self, *, include_files: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "linked_count": self.linked_count,
            "unlinked_count": self.unlinked_count,
            "source_missing_count": self.source_missing_count,
            "total": self.total,
            "target_dir": self.target_dir_rel,
            "extra_library_files": [
                {
                    "name": ef.name,
                    "relative_path": ef.relative_path,
                    "size_bytes": ef.size_bytes,
                }
                for ef in self.extra_library_files
            ],
        }
        if include_files:
            payload["files"] = [
                {
                    "name": f.name,
                    "source": f.source,
                    "size_bytes": f.size_bytes,
                    "status": f.status,
                    **({"library_paths": f.library_paths} if f.library_paths else {}),
                }
                for f in self.files
            ]
        return payload


def load_staging_excludes(config_root: Path) -> set[str]:
    path = config_root / "exclude.txt"
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def is_excluded(book: FlatBook, excludes: set[str]) -> bool:
    if not excludes:
        return False
    candidates = {book.flatten_target, book.source_path, book.top_level_pack}
    return bool(candidates & excludes)


def build_inode_index(
    library_root: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    cancel_check_interval: int = 500,
    on_progress: Callable[[int], None] | None = None,
    progress_interval: int = 50,
    workers: int | None = None,
) -> dict[int, list[str]]:
    from stager_core.target_index import build_target_indexes

    _, inode_index = build_target_indexes(
        library_root,
        should_cancel=should_cancel,
        cancel_check_interval=cancel_check_interval,
        on_progress=on_progress,
        progress_interval=progress_interval,
        workers=workers,
    )
    return inode_index


def _resolve_target_dir_rel(
    library_root: Path,
    author: str,
    title: str,
    staged_path_rel: str | None,
    linked_paths: list[str],
) -> str:
    rel = (staged_path_rel or "").strip().replace("\\", "/")
    if rel:
        return rel
    if linked_paths:
        return linked_paths[0].rsplit("/", 1)[0]
    _, author_dir, title_name = resolve_staging_target(library_root, author, title)
    return f"{author_dir}/{title_name}"


def _collect_extra_library_files(
    library_root: Path,
    target_dir_rel: str,
    source_inodes: set[int],
) -> list[ExtraLibraryFile]:
    if not target_dir_rel or not source_inodes:
        return []
    target_dir = library_root / target_dir_rel.replace("/", os.sep)
    if not target_dir.is_dir():
        return []
    extras: list[ExtraLibraryFile] = []
    for path in target_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXT:
            continue
        ino = source_inode(path)
        if ino is None or ino in source_inodes:
            continue
        rel = str(path.relative_to(library_root)).replace("\\", "/")
        extras.append(
            ExtraLibraryFile(
                name=path.name,
                relative_path=rel,
                size_bytes=path.stat().st_size,
            )
        )
    extras.sort(key=lambda ef: ef.relative_path)
    return extras


def analyze_book_staging(
    source: Path,
    book: FlatBook,
    inode_index: dict[int, list[str]],
    *,
    library_root: Path | None = None,
    author: str = "",
    title: str = "",
    staged_path_rel: str | None = None,
) -> StagingAnalysis:
    file_statuses: list[StagingFileStatus] = []
    linked_paths: list[str] = []
    linked = 0
    unlinked = 0
    source_missing = 0
    source_inodes: set[int] = set()

    for af in book.files:
        src = source / af.source.replace("/", os.sep)
        ino = source_inode(src)
        if ino is None:
            source_missing += 1
            file_statuses.append(
                StagingFileStatus(
                    name=af.name,
                    source=af.source,
                    size_bytes=af.size_bytes,
                    status="source_missing",
                )
            )
            continue
        source_inodes.add(ino)
        if ino in inode_index:
            paths = list(inode_index[ino])
            linked += 1
            linked_paths.extend(paths)
            file_statuses.append(
                StagingFileStatus(
                    name=af.name,
                    source=af.source,
                    size_bytes=af.size_bytes,
                    status="linked",
                    library_paths=paths,
                )
            )
        else:
            unlinked += 1
            file_statuses.append(
                StagingFileStatus(
                    name=af.name,
                    source=af.source,
                    size_bytes=af.size_bytes,
                    status="unlinked",
                )
            )

    total = len(book.files)
    if total == 0:
        detail = "empty_book"
    elif linked == total:
        detail = "already_staged"
    elif linked > 0:
        detail = "partial_staged"
    else:
        detail = "not_staged"

    target_dir_rel = ""
    extra_files: list[ExtraLibraryFile] = []
    if library_root is not None:
        target_dir_rel = _resolve_target_dir_rel(
            library_root, author, title, staged_path_rel, linked_paths
        )
        extra_files = _collect_extra_library_files(
            library_root, target_dir_rel, source_inodes
        )

    return StagingAnalysis(
        linked_count=linked,
        unlinked_count=unlinked,
        source_missing_count=source_missing,
        total=total,
        target_dir_rel=target_dir_rel,
        detail=detail,
        linked_paths=linked_paths,
        files=file_statuses,
        extra_library_files=extra_files,
    )


def book_already_staged(
    source: Path, book: FlatBook, inode_index: dict[int, list[str]]
) -> tuple[bool, str, list[str]]:
    analysis = analyze_book_staging(source, book, inode_index)
    if analysis.detail == "empty_book":
        return False, "empty_book", []
    if analysis.detail == "already_staged":
        return True, "already_staged", analysis.linked_paths
    if analysis.detail == "partial_staged":
        return False, "partial_staged", analysis.linked_paths
    return False, "not_staged", []


def format_title_folder(title: str, series_index: str = "") -> str:
    """Sanitized title folder, optionally prefixed with series index."""
    base = sanitize_folder_name(title or "Untitled")
    idx = (series_index or "").strip()
    if idx:
        return f"{idx} - {base}"
    return base


def compute_target_key(
    author: str,
    title: str,
    series: str = "",
    series_index: str = "",
) -> str:
    author_dir = sanitize_folder_name(author or "Unknown Author")
    if not (series or "").strip():
        title_dir = sanitize_folder_name(title or "Untitled")
        return f"{author_dir}/{title_dir}"
    series_dir = sanitize_folder_name(series)
    title_name = format_title_folder(title, series_index)
    return f"{author_dir}/{series_dir}/{title_name}"


def resolve_staging_target(
    library_root: Path,
    author: str,
    title: str,
    series: str = "",
    series_index: str = "",
) -> tuple[Path, str, str]:
    author_dir = sanitize_folder_name(author or "Unknown Author")
    if not (series or "").strip():
        title_name = sanitize_folder_name(title or "Untitled")
        target_dir = library_root / author_dir / title_name
        return target_dir, author_dir, title_name

    series_dir = sanitize_folder_name(series)
    title_name = format_title_folder(title, series_index)
    rel_suffix = f"{series_dir}/{title_name}"
    target_dir = library_root / author_dir / series_dir / title_name
    return target_dir, author_dir, rel_suffix


def resolve_author_title_paths(
    library_root: Path,
    author: str,
    title: str,
    context_parts: list[str] | None = None,
    used_titles: set[str] | None = None,
) -> tuple[Path, str, str]:
    _ = context_parts, used_titles
    return resolve_staging_target(library_root, author, title)


def _classify_error(msg: str) -> str:
    if "name_collision" in msg:
        return "name_collision"
    if "source_missing" in msg:
        return "source_missing"
    return "link_error"


def stage_book_author_title(
    source: Path,
    library_root: Path,
    book: FlatBook,
    author: str,
    title: str,
    inode_index: dict[int, list[str]],
    used_titles: set[str] | None = None,
    dry_run: bool = False,
    *,
    series: str = "",
    series_index: str = "",
) -> BookResult:
    started = time.perf_counter()
    _ = used_titles
    target_dir, author_dir, rel_suffix = resolve_staging_target(
        library_root, author, title, series, series_index
    )
    rel_target = f"{author_dir}/{rel_suffix}"

    result = BookResult(
        book_id=book.id,
        author=author_dir,
        title=rel_suffix,
        source_path=book.source_path,
        target_path=rel_target,
        status="pending",
    )

    already, detail, _paths = book_already_staged(source, book, inode_index)
    if already:
        result.status = detail
        result.files_skipped = len(book.files)
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    if detail == "partial_staged":
        result.status = "partial_staged"
        result.error = "some files already linked in library; review in UI"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    if dry_run:
        result.status = "dry_run"
        result.files_linked = len(book.files)
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    created_dir = False
    try:
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            created_dir = True

        for af in book.files:
            src = source / af.source.replace("/", os.sep)
            dst = target_dir / af.name

            if not src.is_file():
                raise OSError(f"source_missing: {src}")

            if dst.exists():
                if same_inode(src, dst):
                    result.files_skipped += 1
                    ino = source_inode(src)
                    if ino is not None:
                        inode_index.setdefault(ino, []).append(
                            str(dst.relative_to(library_root)).replace("\\", "/")
                        )
                    continue
                raise OSError(f"name_collision: {dst} exists with different inode")

            os.link(src, dst)
            result.files_linked += 1
            ino = source_inode(src)
            if ino is not None:
                inode_index.setdefault(ino, []).append(
                    str(dst.relative_to(library_root)).replace("\\", "/")
                )

        result.status = "staged"
    except OSError as exc:
        result.status = _classify_error(str(exc))
        result.error = str(exc)
        if created_dir and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
        elif target_dir.is_dir() and not any(target_dir.iterdir()):
            target_dir.rmdir()
    except Exception as exc:
        result.status = "failed"
        result.error = str(exc)
        if created_dir and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def complete_partial_stage(
    source: Path,
    library_root: Path,
    book: FlatBook,
    author: str,
    title: str,
    inode_index: dict[int, list[str]],
    staged_path_rel: str,
    *,
    series: str = "",
    series_index: str = "",
) -> BookResult:
    started = time.perf_counter()
    analysis = analyze_book_staging(
        source,
        book,
        inode_index,
        library_root=library_root,
        author=author,
        title=title,
        staged_path_rel=staged_path_rel,
    )
    target_dir_rel = analysis.target_dir_rel
    _, author_dir, rel_suffix = resolve_staging_target(
        library_root, author, title, series, series_index
    )
    result = BookResult(
        book_id=book.id,
        author=author_dir,
        title=rel_suffix,
        source_path=book.source_path,
        target_path=target_dir_rel or f"{author_dir}/{rel_suffix}",
        status="pending",
    )

    if analysis.detail == "empty_book":
        result.status = "empty_book"
        result.error = "empty book"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
    if analysis.detail == "already_staged":
        result.status = "staged"
        result.files_skipped = analysis.total
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
    if analysis.detail != "partial_staged":
        result.status = "not_staged"
        result.error = "book is not partially staged"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    if not target_dir_rel:
        result.status = "failed"
        result.error = "no target directory for partial staging"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    target_dir = library_root / target_dir_rel.replace("/", os.sep)
    created_dir = False
    try:
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            created_dir = True

        for fs in analysis.files:
            if fs.status != "unlinked":
                continue
            src = source / fs.source.replace("/", os.sep)
            dst = target_dir / fs.name

            if not src.is_file():
                raise OSError(f"source_missing: {src}")

            if dst.exists():
                if same_inode(src, dst):
                    result.files_skipped += 1
                    ino = source_inode(src)
                    if ino is not None:
                        rel = str(dst.relative_to(library_root)).replace("\\", "/")
                        if rel not in inode_index.get(ino, []):
                            inode_index.setdefault(ino, []).append(rel)
                    continue
                raise OSError(f"name_collision: {dst} exists with different inode")

            os.link(src, dst)
            result.files_linked += 1
            ino = source_inode(src)
            if ino is not None:
                inode_index.setdefault(ino, []).append(
                    str(dst.relative_to(library_root)).replace("\\", "/")
                )

        post = analyze_book_staging(
            source,
            book,
            inode_index,
            library_root=library_root,
            author=author,
            title=title,
            staged_path_rel=target_dir_rel,
        )
        if post.detail == "already_staged":
            result.status = "staged"
        else:
            result.status = "partial_staged"
            if post.source_missing_count:
                result.error = f"{post.unlinked_count} file(s) still unlinked; {post.source_missing_count} source missing"
            else:
                result.error = f"{post.unlinked_count} file(s) still unlinked"
    except OSError as exc:
        result.status = _classify_error(str(exc))
        result.error = str(exc)
        if created_dir and target_dir.is_dir() and not any(target_dir.iterdir()):
            target_dir.rmdir()
    except Exception as exc:
        result.status = "failed"
        result.error = str(exc)
        if created_dir and target_dir.is_dir() and not any(target_dir.iterdir()):
            target_dir.rmdir()

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def remove_extra_library_files(
    source: Path,
    library_root: Path,
    book: FlatBook,
    target_dir_rel: str,
    inode_index: dict[int, list[str]],
) -> BookResult:
    started = time.perf_counter()
    rel = (target_dir_rel or "").strip().replace("\\", "/")
    result = BookResult(
        book_id=book.id,
        author="",
        title="",
        source_path=book.source_path,
        target_path=rel,
        status="pending",
    )
    if not rel:
        result.status = "failed"
        result.error = "no target directory"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    analysis = analyze_book_staging(
        source,
        book,
        inode_index,
        library_root=library_root,
        staged_path_rel=rel,
    )
    if not analysis.extra_library_files:
        result.status = "no_extras"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    target_dir = library_root / rel.replace("/", os.sep)
    removed = 0
    try:
        _assert_target_under_library(library_root, target_dir)
        for extra in analysis.extra_library_files:
            path = library_root / extra.relative_path.replace("/", os.sep)
            if not path.is_file():
                continue
            ino = source_inode(path)
            path.unlink()
            removed += 1
            if ino is not None and ino in inode_index:
                rel_path = extra.relative_path
                inode_index[ino] = [p for p in inode_index[ino] if p != rel_path]
                if not inode_index[ino]:
                    del inode_index[ino]

        _prune_empty_dirs_up_to(target_dir, library_root.resolve())
        result.files_linked = removed
        result.status = "removed_extras"
    except (OSError, ValueError) as exc:
        result.status = "failed"
        result.error = str(exc)

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def _prune_empty_dirs_up_to(start: Path, stop: Path) -> None:
    current = start
    while current != stop and current.is_dir():
        if any(current.iterdir()):
            break
        parent = current.parent
        current.rmdir()
        current = parent


def _assert_target_under_library(library_root: Path, target_dir: Path) -> None:
    lib_resolved = library_root.resolve()
    target_resolved = target_dir.resolve()
    if target_resolved == lib_resolved:
        raise ValueError("target path must be below library root")
    target_resolved.relative_to(lib_resolved)


def replace_library_target(library_root: Path, author: str, title: str) -> BookResult:
    started = time.perf_counter()
    target_dir, author_dir, title_name = resolve_staging_target(library_root, author, title)
    rel_target = f"{author_dir}/{title_name}"
    result = BookResult(
        book_id="",
        author=author_dir,
        title=title_name,
        source_path="",
        target_path=rel_target,
        status="pending",
    )
    try:
        _assert_target_under_library(library_root, target_dir)
    except ValueError as exc:
        result.status = "failed"
        result.error = str(exc)
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    if not target_dir.is_dir():
        result.status = "replaced"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    removed = 0
    try:
        for path in target_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXT:
                continue
            path.unlink()
            removed += 1
        _prune_empty_dirs_up_to(target_dir, library_root.resolve())
        result.files_linked = removed
        result.status = "replaced"
    except OSError as exc:
        result.status = "failed"
        result.error = str(exc)

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def unstage_book(
    source: Path,
    library_root: Path,
    book: FlatBook,
    staged_path_rel: str,
) -> BookResult:
    started = time.perf_counter()
    rel = (staged_path_rel or "").strip().replace("\\", "/")
    result = BookResult(
        book_id=book.id,
        author="",
        title="",
        source_path=book.source_path,
        target_path=rel,
        status="pending",
    )
    if not rel:
        result.status = "not_staged"
        result.error = "no staged_path"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    target_dir = library_root / rel.replace("/", os.sep)
    removed = 0
    try:
        for af in book.files:
            src = source / af.source.replace("/", os.sep)
            dst = target_dir / af.name
            if not dst.is_file():
                continue
            if not src.is_file():
                result.status = "source_missing"
                result.error = f"source_missing: {src}"
                result.duration_ms = int((time.perf_counter() - started) * 1000)
                return result
            if not same_inode(src, dst):
                result.status = "inode_mismatch"
                result.error = f"inode_mismatch: {dst}"
                result.duration_ms = int((time.perf_counter() - started) * 1000)
                return result
            dst.unlink()
            removed += 1

        current = target_dir
        while current != library_root and current.is_dir():
            if any(current.iterdir()):
                break
            parent = current.parent
            current.rmdir()
            current = parent

        result.files_linked = removed
        if removed == 0:
            result.status = "not_staged"
            result.error = "no library hardlinks removed"
        else:
            result.status = "unstaged"
    except OSError as exc:
        result.status = "failed"
        result.error = str(exc)

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def _unique_staged_name(
    basename: str,
    used_names: set[str],
    prefix: str,
) -> str:
    if basename not in used_names:
        return basename
    candidate = f"{prefix}_{basename}" if prefix else basename
    if candidate not in used_names:
        return candidate
    stem = Path(basename).stem
    suffix = Path(basename).suffix
    seq = 2
    while True:
        candidate = f"{prefix}_{stem}_{seq}{suffix}" if prefix else f"{stem}_{seq}{suffix}"
        if candidate not in used_names:
            return candidate
        seq += 1


def _book_part_label(book: FlatBook) -> str:
    return (
        book.flatten_name
        or (book.source_path.split("/")[-1] if book.source_path else "")
        or book.id
    )


def resolve_merged_staged_names(
    primary_flatbook: FlatBook,
    member_flatbooks: list[FlatBook],
    staged_name_overrides: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str | int]]]:
    overrides = staged_name_overrides or {}
    staged_files: list[dict[str, str]] = []
    used_names: set[str] = set()
    basename_counts: dict[str, int] = {}

    for book in [primary_flatbook, *member_flatbooks]:
        part_label = _book_part_label(book)
        for af in book.files:
            basename = af.name
            basename_counts[basename] = basename_counts.get(basename, 0) + 1
            if af.source in overrides:
                staged_name = overrides[af.source].strip()
            else:
                staged_name = _unique_staged_name(af.name, used_names, part_label)
            used_names.add(staged_name)
            staged_files.append(
                {
                    "source": af.source,
                    "staged_name": staged_name,
                    "part_label": part_label,
                    "book_id": book.id,
                    "basename": basename,
                }
            )

    filename_conflicts = [
        {"basename": name, "count": count}
        for name, count in sorted(basename_counts.items())
        if count > 1
    ]
    return staged_files, filename_conflicts


def stage_merged_books(
    source: Path,
    library_root: Path,
    primary_flatbook: FlatBook,
    member_flatbooks: list[FlatBook],
    author: str,
    title: str,
    inode_index: dict[int, list[str]],
    staged_name_overrides: dict[str, str] | None = None,
    *,
    series: str = "",
    series_index: str = "",
) -> BookResult:
    started = time.perf_counter()
    target_dir, author_dir, rel_suffix = resolve_staging_target(
        library_root, author, title, series, series_index
    )
    rel_target = f"{author_dir}/{rel_suffix}"

    result = BookResult(
        book_id=primary_flatbook.id,
        author=author_dir,
        title=rel_suffix,
        source_path=primary_flatbook.source_path,
        target_path=rel_target,
        status="pending",
    )

    overrides = {
        source: name.strip()
        for source, name in (staged_name_overrides or {}).items()
        if name.strip()
    }
    staged_files, _ = resolve_merged_staged_names(
        primary_flatbook,
        member_flatbooks,
        staged_name_overrides=overrides if overrides else None,
    )
    staged_names = [entry["staged_name"] for entry in staged_files]
    if any(not name for name in staged_names):
        result.status = "failed"
        result.error = "empty staged filename"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
    if len(staged_names) != len(set(staged_names)):
        result.status = "name_collision"
        result.error = "duplicate staged filenames"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    link_plan: list[tuple[Path, Path]] = []
    for entry in staged_files:
        src = source / entry["source"].replace("/", os.sep)
        link_plan.append((src, target_dir / entry["staged_name"]))

    created_dir = False
    try:
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
            created_dir = True

        for src, dst in link_plan:
            if not src.is_file():
                raise OSError(f"source_missing: {src}")

            if dst.exists():
                if same_inode(src, dst):
                    result.files_skipped += 1
                    ino = source_inode(src)
                    if ino is not None:
                        rel = str(dst.relative_to(library_root)).replace("\\", "/")
                        if rel not in inode_index.get(ino, []):
                            inode_index.setdefault(ino, []).append(rel)
                    continue
                raise OSError(f"name_collision: {dst} exists with different inode")

            os.link(src, dst)
            result.files_linked += 1
            ino = source_inode(src)
            if ino is not None:
                inode_index.setdefault(ino, []).append(
                    str(dst.relative_to(library_root)).replace("\\", "/")
                )

        result.status = "staged"
    except OSError as exc:
        result.status = _classify_error(str(exc))
        result.error = str(exc)
        if created_dir and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
        elif target_dir.is_dir() and not any(target_dir.iterdir()):
            target_dir.rmdir()
    except Exception as exc:
        result.status = "failed"
        result.error = str(exc)
        if created_dir and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result
