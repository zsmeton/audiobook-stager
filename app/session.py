from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from stager_core.conflicts import LibrarySide, detect_conflict_groups
from stager_core.merges import detect_merge_groups
from stager_core.discovery import FlatBook
from stager_core.metadata.library_vocab import LibraryVocabulary
from stager_core.metadata.lvi import build_lvi_rows_from_db
from stager_core.staging import (
    BookResult,
    compute_target_key,
    source_inode,
)
from stager_core.target_index import build_target_indexes

from app.db import (
    DB_LOCK,
    count_books,
    delete_library_target,
    get_session_meta,
    load_conflict_resolutions,
    load_library_targets,
    row_to_book,
    save_library_targets,
    update_session_meta,
    upsert_library_target,
)

STALE_SCAN_HOURS = 24


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StagingSession:
    def __init__(self, books_root: Path, library_root: Path):
        self.books_root = books_root
        self.library_root = library_root
        self.library_index: dict[str, LibrarySide] = {}
        self.lvi: LibraryVocabulary | None = None
        self.lvi_rows: list[dict[str, Any]] = []
        self.inode_index: dict[int, list[str]] = {}
        self.conflict_groups: list[dict[str, Any]] = []
        self.conflict_ids: set[str] = set()
        self.merge_groups: list[dict[str, Any]] = []
        self.merge_ids: set[str] = set()
        self.built_at: str | None = None
        self.scan_id: str | None = None
        self.session_ready = False
        self.stale = True

    def rebuild_target_indexes(
        self,
        scan_id: str | None = None,
        *,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[int], None] | None = None,
        progress_interval: int = 50,
    ) -> None:
        self.library_index, self.inode_index = build_target_indexes(
            self.library_root,
            should_cancel=should_cancel,
            on_progress=on_progress,
            progress_interval=progress_interval,
        )
        self.scan_id = scan_id
        self.built_at = _utcnow()
        self.session_ready = True
        self.stale = False

    def rebuild_lvi(self, conn: sqlite3.Connection) -> None:
        self.lvi_rows = build_lvi_rows_from_db(conn)
        self.lvi = LibraryVocabulary.build_from_rows(self.lvi_rows)

    def hydrate_target_indexes(
        self,
        library_index: dict[str, LibrarySide],
        inode_index: dict[int, list[str]],
        *,
        scan_id: str | None = None,
        built_at: str | None = None,
    ) -> None:
        self.library_index = library_index
        self.inode_index = {ino: list(paths) for ino, paths in inode_index.items()}
        self.scan_id = scan_id
        self.built_at = built_at or _utcnow()
        self.session_ready = True
        self.stale = False

    def get_inode_index_copy(self) -> dict[int, list[str]]:
        return {ino: list(paths) for ino, paths in self.inode_index.items()}

    def merge_inode_index(self, updated: dict[int, list[str]]) -> None:
        for ino, paths in updated.items():
            merged = set(self.inode_index.get(ino, []))
            merged.update(paths)
            self.inode_index[ino] = sorted(merged)

    def apply_unstage(self, book: FlatBook, staged_path_rel: str, conn: sqlite3.Connection | None = None) -> None:
        rel = (staged_path_rel or "").strip().replace("\\", "/")
        if not rel:
            return
        file_rels = {f"{rel}/{af.name}" for af in book.files}
        names = {af.name for af in book.files}
        for ino, paths in list(self.inode_index.items()):
            remaining = [p for p in paths if p not in file_rels]
            if remaining:
                self.inode_index[ino] = remaining
            else:
                del self.inode_index[ino]
        if rel in self.library_index:
            side = self.library_index[rel]
            side.files = [f for f in side.files if f["name"] not in names]
            if not side.files:
                del self.library_index[rel]
        if conn is not None:
            self.persist_library_target(conn, rel)

    def apply_replace_library(self, author: str, title: str, conn: sqlite3.Connection | None = None) -> None:
        target_key = compute_target_key(author, title)
        side = self.library_index.pop(target_key, None)
        if not side:
            return
        paths_to_remove = {f["relative_path"] for f in side.files}
        for ino, paths in list(self.inode_index.items()):
            remaining = [p for p in paths if p not in paths_to_remove]
            if remaining:
                self.inode_index[ino] = remaining
            else:
                del self.inode_index[ino]
        if conn is not None:
            self.persist_library_target(conn, target_key)

    def apply_stage(self, book: FlatBook, result: BookResult, conn: sqlite3.Connection | None = None) -> None:
        if result.status not in {"staged", "already_staged"}:
            return
        target_key = result.target_path
        side = self.library_index.setdefault(target_key, LibrarySide(target_key=target_key))
        existing_paths = {f["relative_path"] for f in side.files}
        for af in book.files:
            rel = f"{target_key}/{af.name}"
            if rel not in existing_paths:
                side.files.append(
                    {
                        "name": af.name,
                        "relative_path": rel,
                        "size_bytes": af.size_bytes,
                        "format": Path(af.name).suffix.lower(),
                    }
                )
                existing_paths.add(rel)
            src = self.books_root / af.source.replace("/", os.sep)
            ino = source_inode(src)
            if ino is not None:
                paths = self.inode_index.setdefault(ino, [])
                if rel not in paths:
                    paths.append(rel)
        if conn is not None:
            self.persist_library_target(conn, target_key)

    def refresh_conflicts(self, conn: sqlite3.Connection) -> None:
        with DB_LOCK:
            rows = conn.execute("SELECT * FROM books ORDER BY source_path").fetchall()
            persisted = load_conflict_resolutions(conn)
        book_dicts = [row_to_book(r) for r in rows]
        self.conflict_groups, self.conflict_ids = detect_conflict_groups(
            book_dicts,
            self.library_root,
            self.books_root,
            persisted,
            self.library_index,
            self.inode_index,
        )

    def refresh_merges(self, conn: sqlite3.Connection) -> None:
        with DB_LOCK:
            rows = conn.execute("SELECT * FROM books ORDER BY source_path").fetchall()
        book_dicts = [row_to_book(r) for r in rows]
        self.merge_groups, self.merge_ids = detect_merge_groups(
            book_dicts,
            self.library_root,
            self.books_root,
            self.library_index,
            self.inode_index,
        )

    def refresh_resolution_groups(self, conn: sqlite3.Connection) -> None:
        self.refresh_conflicts(conn)
        self.refresh_merges(conn)

    def get_conflicts(self) -> tuple[list[dict[str, Any]], set[str]]:
        return self.conflict_groups, self.conflict_ids

    def get_merges(self) -> tuple[list[dict[str, Any]], set[str]]:
        return self.merge_groups, self.merge_ids

    def build_inode_index_from_library_index(self) -> dict[int, list[str]]:
        index: dict[int, list[str]] = {}
        for side in self.library_index.values():
            for file_info in side.files:
                rel = file_info.get("relative_path") or ""
                if not rel:
                    continue
                path = self.library_root / rel.replace("/", os.sep)
                ino = source_inode(path)
                if ino is None:
                    continue
                index.setdefault(ino, [])
                if rel not in index[ino]:
                    index[ino].append(rel)
        return index

    def persist_scan_snapshot(
        self,
        conn: sqlite3.Connection,
        *,
        scan_id: str,
        source_book_count: int,
        finished_at: str | None = None,
    ) -> None:
        finished = finished_at or _utcnow()
        with DB_LOCK:
            save_library_targets(conn, self.library_index)
            update_session_meta(
                conn,
                last_scan_id=scan_id,
                last_scan_finished_at=finished,
                last_source_discovery_at=finished,
                source_book_count=source_book_count,
                library_target_count=len(self.library_index),
            )

    def persist_library_target(self, conn: sqlite3.Connection, target_key: str) -> None:
        side = self.library_index.get(target_key)
        with DB_LOCK:
            if side and side.files:
                upsert_library_target(conn, side)
            else:
                delete_library_target(conn, target_key)
            update_session_meta(
                conn,
                library_target_count=len(self.library_index),
            )

    @classmethod
    def try_hydrate_from_db(
        cls,
        conn: sqlite3.Connection,
        books_root: Path,
        library_root: Path,
    ) -> StagingSession | None:
        with DB_LOCK:
            meta = get_session_meta(conn)
            finished_at = meta.get("last_scan_finished_at")
            if not finished_at:
                return None
            try:
                finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            except ValueError:
                return None
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - finished
            if age > timedelta(hours=STALE_SCAN_HOURS):
                return None
            if count_books(conn) <= 0:
                return None
            library_index = load_library_targets(conn)
            if not library_index:
                return None

        session = cls(books_root, library_root)
        session.library_index = library_index
        session.inode_index = session.build_inode_index_from_library_index()
        session.scan_id = meta.get("last_scan_id")
        session.built_at = finished_at
        session.session_ready = True
        session.stale = False
        session.refresh_resolution_groups(conn)
        session.rebuild_lvi(conn)
        return session
