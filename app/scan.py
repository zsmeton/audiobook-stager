from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from stager_core.discovery import DiscoveryCancelled, FlatBook, discover_books
from stager_core.metadata.lookup import LviLookupOptions, MetadataLookupService
from stager_core.metadata.lvi import lvi_for_book
from stager_core.metadata.title_extraction import TitleExtractionConfig, config_from_settings
from stager_core.metadata.effective import effective_author, effective_title
from stager_core.metadata.types import ManualHints
from stager_core.staging import book_already_staged
from stager_core.target_index import build_target_indexes

from app.db import (
    DB_LOCK,
    _utcnow,
    delete_books_by_ids,
    find_metadata_donor_row,
    get_auto_settings,
    insert_lookup_decision,
    migrate_orphan_book_metadata,
    update_auto_settings,
)
from app.fingerprint_cache import OverlayFingerprintCache, SqliteFingerprintCache
from app.session import StagingSession

logger = logging.getLogger(__name__)


def _log_stage(scan_id: str, stage: str, started: float, **details: int | str) -> None:
    elapsed = time.perf_counter() - started
    suffix = ", ".join(f"{key}={value}" for key, value in details.items())
    if suffix:
        logger.info("scan %s %s: %.1fs (%s)", scan_id, stage, elapsed, suffix)
    else:
        logger.info("scan %s %s: %.1fs", scan_id, stage, elapsed)


def _manual_hints_from_row(row_dict: dict) -> ManualHints | None:
    manual = ManualHints(
        author=effective_author(row_dict) if int(row_dict.get("chosen_author_set") or 0) else "",
        title=effective_title(row_dict, flatten_name=row_dict.get("flatten_name") or "")
        if int(row_dict.get("chosen_title_set") or 0)
        else "",
    )
    if not manual.author and not manual.title:
        return None
    return manual


class ScanProgress:
    PHASE_DISCOVERING = "discovering"
    PHASE_INDEXING = "indexing"
    PHASE_METADATA = "metadata"

    def __init__(
        self,
        conn: sqlite3.Connection,
        scan_id: str,
        *,
        flush_interval_s: float = 0.4,
    ):
        self._conn = conn
        self._scan_id = scan_id
        self._lock = threading.Lock()
        self._flush_interval_s = flush_interval_s
        self._last_flush = 0.0
        self._dirty = False
        self._phase = self.PHASE_DISCOVERING
        self._message = "Discovering books..."
        self._counters = {
            "books_discovered": 0,
            "books_tagged": 0,
            "books_indexed": 0,
            "books_metadata": 0,
            "books_complete": 0,
            "library_files_indexed": 0,
            "total_books": 0,
        }

    def set_phase(self, phase: str, message: str = "") -> None:
        with self._lock:
            self._phase = phase
            if message:
                self._message = message
            self._dirty = True
            self._flush_locked(force=True)

    def set_discovered(self, count: int, message: str = "") -> None:
        with self._lock:
            self._counters["books_discovered"] = max(
                self._counters["books_discovered"], count
            )
            if message:
                self._message = message
            self._dirty = True
            self._flush_locked()

    def set_library_files_indexed(self, count: int) -> None:
        with self._lock:
            self._counters["library_files_indexed"] = max(
                self._counters["library_files_indexed"], count
            )
            self._dirty = True
            self._flush_locked()

    def set_total_books(self, total: int, message: str = "") -> None:
        with self._lock:
            self._counters["total_books"] = total
            self._counters["books_discovered"] = max(
                self._counters["books_discovered"], total
            )
            if message:
                self._message = message
            self._dirty = True
            self._flush_locked(force=True)

    def inc(self, field: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[field] = self._counters.get(field, 0) + amount
            self._dirty = True
            self._flush_locked()

    def set_message(self, message: str) -> None:
        with self._lock:
            self._message = message
            self._dirty = True
            self._flush_locked()

    def flush(self, *, force: bool = False) -> None:
        with self._lock:
            self._flush_locked(force=force)

    def _flush_locked(self, *, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        now = time.perf_counter()
        if not force and (now - self._last_flush) < self._flush_interval_s:
            return
        self._last_flush = now
        self._dirty = False
        discovered = self._counters["books_discovered"]
        complete = self._counters["books_complete"]
        with DB_LOCK:
            self._conn.execute(
                """
                UPDATE scans
                SET books_discovered = ?,
                    books_found = ?,
                    books_tagged = ?,
                    books_indexed = ?,
                    books_metadata = ?,
                    books_complete = ?,
                    metadata_done = ?,
                    library_files_indexed = ?,
                    total_books = ?,
                    scan_phase = ?,
                    message = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    discovered,
                    discovered,
                    self._counters["books_tagged"],
                    self._counters["books_indexed"],
                    self._counters["books_metadata"],
                    complete,
                    complete,
                    self._counters["library_files_indexed"],
                    self._counters["total_books"],
                    self._phase,
                    self._message,
                    self._scan_id,
                ),
            )
            self._conn.commit()


class ScanAlreadyRunning(Exception):
    def __init__(self, scan_id: str):
        self.scan_id = scan_id
        super().__init__(f"scan {scan_id} already in progress")


class ScanManager:
    def __init__(
        self,
        conn: sqlite3.Connection,
        books_root: Path,
        library_root: Path,
        session: StagingSession | None = None,
    ):
        self.conn = conn
        self.books_root = books_root
        self.library_root = library_root
        self.session = session
        self.lookup = MetadataLookupService(conn)
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._reconcile_stale_scans()

    def get_running_scan(self) -> sqlite3.Row | None:
        with DB_LOCK:
            return self.conn.execute(
                "SELECT * FROM scans WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

    def _reconcile_stale_scans(self) -> None:
        if not self.get_running_scan():
            return
        if self._thread is not None and self._thread.is_alive():
            return
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE scans
                SET status = 'failed', finished_at = ?, message = ?
                WHERE status = 'running'
                """,
                (_utcnow(), "Scan interrupted (server restarted)"),
            )
            self.conn.commit()

    def cancel_scan(self, scan_id: str) -> bool:
        row = self.get_running_scan()
        if not row or row["id"] != scan_id:
            return False
        if self._thread is None or not self._thread.is_alive():
            return False
        self._cancel.set()
        self._mark_scan_cancelling(scan_id)
        return True

    def _mark_scan_cancelling(self, scan_id: str) -> None:
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE scans
                SET message = ?
                WHERE id = ? AND status = 'running'
                """,
                ("Cancelling…", scan_id),
            )
            self.conn.commit()

    def _update_scan_message(self, scan_id: str, message: str) -> None:
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE scans
                SET message = ?
                WHERE id = ? AND status = 'running'
                """,
                (message, scan_id),
            )
            self.conn.commit()

    def _mark_scan_cancelled(self, scan_id: str) -> None:
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE scans
                SET status = 'cancelled', finished_at = ?, message = ?
                WHERE id = ? AND status = 'running'
                """,
                (_utcnow(), "Scan cancelled", scan_id),
            )
            self.conn.commit()

    def start_scan(self, auto_run_id: str | None = None) -> str:
        row = self.get_running_scan()
        if row and self._thread is not None and self._thread.is_alive():
            raise ScanAlreadyRunning(row["id"])
        self._cancel.clear()
        scan_id = uuid.uuid4().hex[:12]
        with DB_LOCK:
            self.conn.execute(
                """
                INSERT INTO scans (
                    id, status, started_at, total_books, metadata_done, books_found,
                    books_discovered, books_complete, scan_phase, message
                )
                VALUES (?, 'running', ?, 0, 0, 0, 0, 0, ?, 'Discovering books...')
                """,
                (scan_id, _utcnow(), ScanProgress.PHASE_DISCOVERING),
            )
            self.conn.commit()

        self._thread = threading.Thread(
            target=self._run_scan,
            args=(scan_id, auto_run_id),
            name=f"scan-{scan_id}",
            daemon=True,
        )
        self._thread.start()
        return scan_id

    def _run_scan(self, scan_id: str, auto_run_id: str | None = None) -> None:
        scan_started = time.perf_counter()
        progress = ScanProgress(self.conn, scan_id)
        sqlite_fp_cache = SqliteFingerprintCache(self.conn)
        fp_cache = OverlayFingerprintCache(sqlite_fp_cache)
        try:
            def on_discovery_progress(count: int) -> None:
                if self._cancel.is_set():
                    raise DiscoveryCancelled()
                progress.set_discovered(count, f"Discovering books… {count} found")

            def on_library_progress(count: int) -> None:
                if self._cancel.is_set():
                    raise DiscoveryCancelled()
                progress.set_library_files_indexed(count)

            def run_discovery() -> list[FlatBook]:
                return discover_books(
                    self.books_root,
                    on_progress=on_discovery_progress,
                    should_cancel=self._cancel.is_set,
                    fingerprint_cache=fp_cache,
                )

            def run_indexing() -> dict[int, list[str]] | None:
                if self.session is not None:
                    self.session.rebuild_target_indexes(
                        scan_id,
                        should_cancel=self._cancel.is_set,
                        on_progress=on_library_progress,
                    )
                    with DB_LOCK:
                        self.session.rebuild_lvi(self.conn)
                    return None
                _, inode_index = build_target_indexes(
                    self.library_root,
                    should_cancel=self._cancel.is_set,
                    on_progress=on_library_progress,
                )
                return inode_index

            stage_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"scan-{scan_id}") as pool:
                discovery_future = pool.submit(run_discovery)
                indexing_future = pool.submit(run_indexing)
                books = discovery_future.result()
                progress.set_total_books(len(books))
                inode_index = indexing_future.result()
            if self.session is not None:
                inode_index = self.session.inode_index

            fp_cache.flush()
            pruned = sqlite_fp_cache.prune_missing(self.books_root)
            _log_stage(
                scan_id,
                "discover",
                stage_started,
                books=len(books),
                fp_pruned=pruned,
            )
            if self._cancel.is_set():
                self._mark_scan_cancelled(scan_id)
                return

            index_details: dict[str, int | str] = {"inodes": len(inode_index)}
            if self.session is not None:
                index_details["library_targets"] = len(self.session.library_index)
            _log_stage(scan_id, "indexing", stage_started, **index_details)
            progress.set_total_books(
                len(books),
                f"Found {len(books)} books; looking up metadata...",
            )
            progress.set_phase(ScanProgress.PHASE_METADATA)

            if self._cancel.is_set():
                self._mark_scan_cancelled(scan_id)
                return

            errors = 0
            stage_started = time.perf_counter()
            scan_manual_hints = get_auto_settings(self.conn)["scan_manual_hints"]
            auto_settings = get_auto_settings(self.conn)
            title_extraction = config_from_settings(auto_settings)
            for idx, book in enumerate(books, start=1):
                if self._cancel.is_set():
                    self._mark_scan_cancelled(scan_id)
                    return
                try:
                    self._upsert_book(
                        scan_id,
                        book,
                        inode_index,
                        auto_run_id,
                        scan_manual_hints=scan_manual_hints,
                        lvi_search=auto_settings["lvi_search"],
                        lvi_boost=auto_settings["lvi_boost"],
                        title_extraction=title_extraction,
                        progress=progress,
                    )
                except DiscoveryCancelled:
                    self._mark_scan_cancelled(scan_id)
                    return
                except Exception as exc:
                    errors += 1
                    logger.exception("metadata failed for %s", book.source_path)
                    self._upsert_book_fallback(
                        scan_id, book, inode_index, str(exc), progress=progress
                    )
                wait = self.lookup.wait_status()
                msg = f"Metadata: {idx}/{len(books)}"
                if wait:
                    msg += f" ({wait})"
                if errors:
                    msg += f" · {errors} error(s)"
                progress.set_message(msg)
                progress.flush(force=True)

            _log_stage(
                scan_id,
                "metadata",
                stage_started,
                books=len(books),
                errors=errors,
            )

            stage_started = time.perf_counter()
            self._prune_orphan_books(books)
            _log_stage(scan_id, "prune", stage_started)

            stage_started = time.perf_counter()
            self._reconcile_partial_after_scan()
            _log_stage(scan_id, "reconcile", stage_started)

            finish_msg = f"Scan complete: {len(books)} books"
            if errors:
                finish_msg += f" ({errors} with lookup errors)"
            with DB_LOCK:
                self.conn.execute(
                    """
                    UPDATE scans
                    SET status = 'completed', finished_at = ?, message = ?
                    WHERE id = ?
                    """,
                    (_utcnow(), finish_msg, scan_id),
                )

                if get_auto_settings(self.conn)["cache_relookup_pending"]:
                    update_auto_settings(self.conn, cache_relookup_pending=False)
                else:
                    self.conn.commit()
            if self.session is not None:
                stage_started = time.perf_counter()
                self.session.refresh_conflicts(self.conn)
                finished_row = self.conn.execute(
                    "SELECT finished_at FROM scans WHERE id = ?", (scan_id,)
                ).fetchone()
                finished_at = finished_row["finished_at"] if finished_row else None
                self.session.persist_scan_snapshot(
                    self.conn,
                    scan_id=scan_id,
                    source_book_count=len(books),
                    finished_at=finished_at,
                )
                _log_stage(scan_id, "finalize", stage_started)
            _log_stage(
                scan_id,
                "total",
                scan_started,
                books=len(books),
                errors=errors,
            )
        except DiscoveryCancelled:
            self._mark_scan_cancelled(scan_id)
        except Exception as exc:
            logger.exception("scan %s failed", scan_id)
            with DB_LOCK:
                self.conn.execute(
                    """
                    UPDATE scans
                    SET status = 'failed', finished_at = ?, message = ?
                    WHERE id = ?
                    """,
                    (_utcnow(), str(exc), scan_id),
                )
                self.conn.commit()

    def _lvi_options(
        self,
        book_id: str,
        *,
        lvi_search: bool,
        lvi_boost: bool,
        title_extraction: TitleExtractionConfig | None = None,
    ) -> LviLookupOptions:
        base = self.session.lvi if self.session is not None else None
        rows = self.session.lvi_rows if self.session is not None else None
        lvi = lvi_for_book(base, rows, book_id) if base is not None else None
        if title_extraction is None:
            title_extraction = config_from_settings(get_auto_settings(self.conn))
        return LviLookupOptions(
            lvi=lvi,
            lvi_search=lvi_search,
            lvi_boost=lvi_boost,
            title_extraction=title_extraction,
        )

    def _upsert_book(
        self,
        scan_id: str,
        book: FlatBook,
        inode_index: dict[int, list[str]],
        auto_run_id: str | None = None,
        *,
        scan_manual_hints: bool = False,
        lvi_search: bool = True,
        lvi_boost: bool = True,
        title_extraction: TitleExtractionConfig | None = None,
        progress: ScanProgress | None = None,
    ) -> None:
        already, stage_detail, linked_paths = book_already_staged(
            self.books_root, book, inode_index
        )
        if progress is not None:
            progress.inc("books_indexed")
        status = "pending"
        staged_path = ""
        if already:
            status = "staged"
            staged_path = linked_paths[0].rsplit("/", 1)[0] if linked_paths else ""
        elif stage_detail == "partial_staged":
            status = "partial_staged"
            staged_path = linked_paths[0].rsplit("/", 1)[0] if linked_paths else ""

        # Lookup policy: protect the curated library and cut API load by skipping
        # external lookups for books that are already staged or were skipped;
        # only new/pending books hit the network.
        with DB_LOCK:
            existing = self.conn.execute(
                """
                SELECT status, suggested_author, suggested_title, confidence,
                       candidates_json, tags_json, lookup_status,
                       chosen_author, chosen_title, chosen_author_set, chosen_title_set,
                       flatten_name
                FROM books WHERE id = ?
                """,
                (book.id,),
            ).fetchone()

        # Escape hatch for the sticky-status guard below: a book previously
        # marked 'staged' whose library hardlinks have since disappeared (e.g.
        # files deleted from the library to re-test) must return to the pending
        # queue and get a fresh lookup, instead of staying 'staged' forever.
        destaged = (
            existing is not None
            and existing["status"] == "staged"
            and not already
            and stage_detail != "partial_staged"
        )
        if destaged:
            status = "pending"
            staged_path = ""
            with DB_LOCK:
                self.conn.execute(
                    "UPDATE books SET status = 'pending', staged_path = '' WHERE id = ?",
                    (book.id,),
                )
                self.conn.commit()

        skip_lookup = already or (
            not destaged
            and existing is not None
            and existing["status"] in ("staged", "skipped")
        )

        files_json = json.dumps([asdict(f) for f in book.files])

        decision_log: dict | None = None
        lvi_match_json = "{}"
        chosen_author = ""
        chosen_title = ""
        chosen_series = ""
        chosen_series_index = ""
        chosen_author_set = 0
        chosen_title_set = 0
        chosen_series_set = 0
        chosen_series_index_set = 0
        if skip_lookup:
            donor = None
            if existing is None:
                donor = find_metadata_donor_row(
                    self.conn,
                    source_path=book.source_path,
                    staged_path=staged_path,
                    exclude_id=book.id,
                )
            source = existing if existing is not None else donor
            suggested_author = source["suggested_author"] if source else ""
            suggested_title = (
                source["suggested_title"]
                if source and source["suggested_title"]
                else book.flatten_name
            )
            suggested_series = source["suggested_series"] if source and "suggested_series" in source.keys() else ""
            suggested_series_index = (
                source["suggested_series_index"] if source and "suggested_series_index" in source.keys() else ""
            )
            suggested_series_state = (
                source["suggested_series_state"] if source and "suggested_series_state" in source.keys() else ""
            )
            suggested_series_source = (
                source["suggested_series_source"] if source and "suggested_series_source" in source.keys() else ""
            )
            confidence = source["confidence"] if source else 0.0
            lookup_status = source["lookup_status"] if source else "ok"
            candidates_json = source["candidates_json"] if source else "[]"
            tags_json = source["tags_json"] if source else "{}"
            if donor is not None:
                chosen_author = donor["chosen_author"] or ""
                chosen_title = donor["chosen_title"] or ""
                chosen_series = donor["chosen_series"] or "" if "chosen_series" in donor.keys() else ""
                chosen_series_index = (
                    donor["chosen_series_index"] or "" if "chosen_series_index" in donor.keys() else ""
                )
                chosen_author_set = int(donor["chosen_author_set"] or 0) if "chosen_author_set" in donor.keys() else 0
                chosen_title_set = int(donor["chosen_title_set"] or 0) if "chosen_title_set" in donor.keys() else 0
                chosen_series_set = int(donor["chosen_series_set"] or 0) if "chosen_series_set" in donor.keys() else 0
                chosen_series_index_set = (
                    int(donor["chosen_series_index_set"] or 0)
                    if "chosen_series_index_set" in donor.keys()
                    else 0
                )
        else:
            if self._cancel.is_set():
                raise DiscoveryCancelled()
            manual = None
            if scan_manual_hints and existing is not None:
                manual = _manual_hints_from_row(dict(existing))
            resolution = self.lookup.resolve_book(
                self.books_root,
                book,
                manual=manual,
                lvi_options=self._lvi_options(
                    book.id,
                    lvi_search=lvi_search,
                    lvi_boost=lvi_boost,
                    title_extraction=title_extraction,
                ),
            )
            if progress is not None:
                progress.inc("books_metadata")
            suggested_author = resolution.suggested_author
            suggested_title = resolution.suggested_title
            suggested_series = resolution.suggested_series
            suggested_series_index = resolution.suggested_series_index
            suggested_series_state = resolution.suggested_series_state
            suggested_series_source = resolution.suggested_series_source
            confidence = resolution.confidence
            lookup_status = resolution.lookup_status
            candidates_json = json.dumps([c.to_dict() for c in resolution.candidates])
            tags_json = json.dumps(resolution.tags.to_dict())
            lvi_match_json = json.dumps(resolution.lvi_match)
            decision_log = {
                "breakdown": {
                    **resolution.book_breakdown,
                    "series_breakdown": resolution.series_breakdown,
                    "confidence_breakdown": resolution.confidence_breakdown,
                },
                "search_context": resolution.search_context,
                "tags": resolution.tags.to_dict(),
            }

        if progress is not None:
            progress.inc("books_tagged")

        with DB_LOCK:
            self.conn.execute(
            """
            INSERT INTO books (
                id, scan_id, source_path, source_path_parts, top_level_pack, parent_context,
                grouping, flatten_name, flatten_target, files_json, status,
                suggested_author, suggested_title,
                suggested_series, suggested_series_index, suggested_series_state, suggested_series_source,
                chosen_author, chosen_title,
                chosen_series, chosen_series_index,
                chosen_author_set, chosen_title_set, chosen_series_set, chosen_series_index_set,
                confidence, staged_path,
                tags_json, candidates_json, lookup_status, lvi_match_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                scan_id = excluded.scan_id,
                source_path = excluded.source_path,
                source_path_parts = excluded.source_path_parts,
                top_level_pack = excluded.top_level_pack,
                parent_context = excluded.parent_context,
                grouping = excluded.grouping,
                flatten_name = excluded.flatten_name,
                flatten_target = excluded.flatten_target,
                files_json = excluded.files_json,
                status = CASE
                    WHEN books.status IN ('skipped', 'staged') THEN books.status
                    ELSE excluded.status
                END,
                suggested_author = excluded.suggested_author,
                suggested_title = excluded.suggested_title,
                suggested_series = excluded.suggested_series,
                suggested_series_index = excluded.suggested_series_index,
                suggested_series_state = excluded.suggested_series_state,
                suggested_series_source = excluded.suggested_series_source,
                chosen_author = CASE
                    WHEN COALESCE(books.chosen_author_set, 0) = 1 THEN books.chosen_author
                    ELSE excluded.chosen_author
                END,
                chosen_title = CASE
                    WHEN COALESCE(books.chosen_title_set, 0) = 1 THEN books.chosen_title
                    ELSE excluded.chosen_title
                END,
                chosen_series = CASE
                    WHEN COALESCE(books.chosen_series_set, 0) = 1 THEN books.chosen_series
                    ELSE excluded.chosen_series
                END,
                chosen_series_index = CASE
                    WHEN COALESCE(books.chosen_series_index_set, 0) = 1 THEN books.chosen_series_index
                    ELSE excluded.chosen_series_index
                END,
                confidence = excluded.confidence,
                staged_path = CASE
                    WHEN excluded.staged_path != '' THEN excluded.staged_path
                    ELSE books.staged_path
                END,
                error = CASE
                    WHEN excluded.status = 'staged' THEN ''
                    ELSE books.error
                END,
                tags_json = excluded.tags_json,
                candidates_json = excluded.candidates_json,
                lvi_match_json = excluded.lvi_match_json,
                lookup_status = excluded.lookup_status,
                updated_at = excluded.updated_at
            """,
            (
                book.id,
                scan_id,
                book.source_path,
                json.dumps(book.source_path_parts),
                book.top_level_pack,
                book.parent_context,
                book.grouping,
                book.flatten_name,
                book.flatten_target,
                files_json,
                status,
                suggested_author,
                suggested_title,
                suggested_series,
                suggested_series_index,
                suggested_series_state,
                suggested_series_source,
                chosen_author,
                chosen_title,
                chosen_series,
                chosen_series_index,
                chosen_author_set,
                chosen_title_set,
                chosen_series_set,
                chosen_series_index_set,
                confidence,
                staged_path,
                tags_json,
                candidates_json,
                lookup_status,
                lvi_match_json,
                _utcnow(),
            ),
            )
            self.conn.commit()

        # Append-only decision log: only when an actual lookup ran (pending/new
        # books). Staged/skipped books that skip the lookup leave no row.
        if decision_log is not None:
            insert_lookup_decision(
                self.conn,
                book_id=book.id,
                scan_id=scan_id,
                trigger="auto" if auto_run_id else "scan",
                breakdown=decision_log["breakdown"],
                search_context=decision_log["search_context"],
                tags=decision_log["tags"],
                auto_run_id=auto_run_id,
            )

        if progress is not None:
            progress.inc("books_complete")

    def _upsert_book_fallback(
        self,
        scan_id: str,
        book: FlatBook,
        inode_index: dict[int, list[str]],
        error: str,
        *,
        progress: ScanProgress | None = None,
    ) -> None:
        already, stage_detail, linked_paths = book_already_staged(
            self.books_root, book, inode_index
        )
        if progress is not None:
            progress.inc("books_indexed")
        status = "pending"
        staged_path = ""
        if already:
            status = "staged"
            staged_path = linked_paths[0].rsplit("/", 1)[0] if linked_paths else ""
        elif stage_detail == "partial_staged":
            status = "partial_staged"
            staged_path = linked_paths[0].rsplit("/", 1)[0] if linked_paths else ""

        files_json = json.dumps([asdict(f) for f in book.files])
        with DB_LOCK:
            self.conn.execute(
            """
            INSERT INTO books (
                id, scan_id, source_path, source_path_parts, top_level_pack, parent_context,
                grouping, flatten_name, flatten_target, files_json, status,
                suggested_author, suggested_title, confidence, staged_path,
                tags_json, candidates_json, lookup_status, error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 0, ?, '{}', '[]', 'error', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                scan_id = excluded.scan_id,
                source_path = excluded.source_path,
                files_json = excluded.files_json,
                status = CASE
                    WHEN books.status IN ('skipped', 'staged') THEN books.status
                    ELSE excluded.status
                END,
                suggested_title = excluded.suggested_title,
                lookup_status = excluded.lookup_status,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                book.id,
                scan_id,
                book.source_path,
                json.dumps(book.source_path_parts),
                book.top_level_pack,
                book.parent_context,
                book.grouping,
                book.flatten_name,
                book.flatten_target,
                files_json,
                status,
                book.flatten_name,
                staged_path,
                error,
                _utcnow(),
            ),
            )
            self.conn.commit()

        if progress is not None:
            progress.inc("books_complete")

    def _prune_orphan_books(self, books: list[FlatBook]) -> None:
        discovered = {b.id for b in books}
        with DB_LOCK:
            rows = self.conn.execute("SELECT id, status FROM books").fetchall()
        orphan_rows = [r for r in rows if r["id"] not in discovered]
        orphan_ids = [r["id"] for r in orphan_rows]
        if not orphan_ids:
            return

        status_counts: dict[str, int] = {}
        for row in orphan_rows:
            status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

        migrated = migrate_orphan_book_metadata(self.conn, discovered)
        delete_books_by_ids(self.conn, orphan_ids)

        parts = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
        logger.info(
            "Pruned %d stale book rows (%s); migrated metadata on %d successors",
            len(orphan_ids),
            parts,
            migrated,
        )

    def _reconcile_partial_after_scan(self) -> None:
        from app.api import _maybe_reconcile_partial_row

        with DB_LOCK:
            rows = self.conn.execute(
                "SELECT * FROM books WHERE status = 'partial_staged'"
            ).fetchall()
        for row in rows:
            _maybe_reconcile_partial_row(row)

    def lookup_book_by_id(self, book_id: str, manual: ManualHints | None = None) -> None:
        with DB_LOCK:
            row = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return
        book = self._row_to_flatbook(row)
        row_dict = dict(row)
        if manual is None:
            manual = _manual_hints_from_row(row_dict)
        auto_settings = get_auto_settings(self.conn)
        resolution = self.lookup.resolve_book(
            self.books_root,
            book,
            manual=manual,
            lvi_options=self._lvi_options(
                book.id,
                lvi_search=auto_settings["lvi_search"],
                lvi_boost=auto_settings["lvi_boost"],
                title_extraction=config_from_settings(auto_settings),
            ),
        )
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE books SET
                    suggested_author = ?, suggested_title = ?,
                    suggested_series = ?, suggested_series_index = ?,
                    suggested_series_state = ?, suggested_series_source = ?,
                    confidence = ?,
                    tags_json = ?, candidates_json = ?, lookup_status = ?,
                    lvi_match_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    resolution.suggested_author,
                    resolution.suggested_title,
                    resolution.suggested_series,
                    resolution.suggested_series_index,
                    resolution.suggested_series_state,
                    resolution.suggested_series_source,
                    resolution.confidence,
                    json.dumps(resolution.tags.to_dict()),
                    json.dumps([c.to_dict() for c in resolution.candidates]),
                    resolution.lookup_status,
                    json.dumps(resolution.lvi_match),
                    _utcnow(),
                    book_id,
                ),
            )
            self.conn.commit()

        insert_lookup_decision(
            self.conn,
            book_id=book_id,
            scan_id=row["scan_id"],
            trigger="manual_relookup",
            breakdown={
                **resolution.book_breakdown,
                "series_breakdown": resolution.series_breakdown,
                "confidence_breakdown": resolution.confidence_breakdown,
            },
            search_context=resolution.search_context,
            tags=resolution.tags.to_dict(),
        )

    def _row_to_flatbook(self, row: sqlite3.Row) -> FlatBook:
        from stager_core.discovery import AudioFile

        files = [
            AudioFile(name=f["name"], source=f["source"], size_bytes=f["size_bytes"])
            for f in json.loads(row["files_json"])
        ]
        return FlatBook(
            id=row["id"],
            flatten_name=row["flatten_name"],
            source_path=row["source_path"],
            source_path_parts=json.loads(row["source_path_parts"]),
            top_level_pack=row["top_level_pack"],
            parent_context=row["parent_context"],
            grouping=row["grouping"],
            files=files,
            flatten_target=row["flatten_target"],
        )
