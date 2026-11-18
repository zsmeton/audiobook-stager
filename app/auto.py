from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from typing import Any

from stager_core.auto_eligibility import is_eligible_for_auto_stage
from stager_core.conflicts import detect_conflict_groups, resolve_winner_metadata
from stager_core.discovery import AudioFile, FlatBook
from stager_core.staging import stage_book_author_title

from app.activity_lock import is_activity_lock_active
from app.db import (
    DB_LOCK,
    _utcnow,
    get_auto_settings,
    insert_decision_outcome,
    load_conflict_resolutions,
    row_to_book,
    update_auto_settings,
)
from app.scan import ScanAlreadyRunning, ScanManager
from app.session import StagingSession

logger = logging.getLogger(__name__)


class AutoRunAlreadyRunning(Exception):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"auto-run {run_id} already in progress")


class AutoRunBlocked(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class AutoRunManager:
    def __init__(
        self,
        conn: sqlite3.Connection,
        scan_manager: ScanManager,
        session: StagingSession | None = None,
    ):
        self.conn = conn
        self.scan_manager = scan_manager
        self.session = session
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._reconcile_stale_runs()

    def _reconcile_stale_runs(self) -> None:
        row = self.get_running_run()
        if not row:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        with DB_LOCK:
            self.conn.execute(
                """
                UPDATE auto_runs
                SET status = 'failed', finished_at = ?, message = ?, phase = 'failed'
                WHERE status = 'running'
                """,
                (_utcnow(), "Auto-run interrupted (server restarted)"),
            )
            self.conn.commit()

    def get_running_run(self) -> sqlite3.Row | None:
        with DB_LOCK:
            return self.conn.execute(
                "SELECT * FROM auto_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

    def is_running(self) -> bool:
        row = self.get_running_run()
        return bool(row and self._thread is not None and self._thread.is_alive())

    def can_start_scheduled(self) -> tuple[bool, str]:
        settings = get_auto_settings(self.conn)
        if not settings["enabled"]:
            return False, "disabled"
        if self.is_running():
            return False, "auto_run_running"
        if self.scan_manager.get_running_scan() is not None:
            thread = self.scan_manager._thread
            if thread is not None and thread.is_alive():
                return False, "manual_scan_running"
        if is_activity_lock_active(self.conn):
            return False, "activity_lock_active"
        return True, "ok"

    def start_run(
        self,
        *,
        trigger: str,
        require_enabled: bool = True,
        bypass_activity_lock: bool = False,
    ) -> str:
        if self.is_running():
            row = self.get_running_run()
            raise AutoRunAlreadyRunning(row["id"] if row else "unknown")

        settings = get_auto_settings(self.conn)
        if require_enabled and not settings["enabled"]:
            raise AutoRunBlocked("auto-staging is disabled")

        scan_row = self.scan_manager.get_running_scan()
        if scan_row is not None and self.scan_manager._thread is not None and self.scan_manager._thread.is_alive():
            raise AutoRunBlocked("manual scan already in progress")

        if trigger == "scheduled":
            ok, reason = self.can_start_scheduled()
            if not ok:
                raise AutoRunBlocked(reason)
        elif not bypass_activity_lock and is_activity_lock_active(self.conn):
            raise AutoRunBlocked("activity lock active")

        run_id = uuid.uuid4().hex[:12]
        self._cancel.clear()
        with DB_LOCK:
            self.conn.execute(
                """
                INSERT INTO auto_runs (
                    id, status, trigger, started_at, phase, message
                ) VALUES (?, 'running', ?, ?, 'starting', 'Starting auto-run...')
                """,
                (run_id, trigger, _utcnow()),
            )
            self.conn.commit()

        self._thread = threading.Thread(
            target=self._run_auto,
            args=(run_id,),
            name=f"auto-run-{run_id}",
            daemon=True,
        )
        self._thread.start()
        return run_id

    def cancel_run(self, run_id: str) -> bool:
        row = self.get_running_run()
        if not row or row["id"] != run_id:
            return False
        if self._thread is None or not self._thread.is_alive():
            return False
        self._cancel.set()
        scan_id = row["scan_id"]
        if scan_id:
            self.scan_manager.cancel_scan(scan_id)
        return True

    def _mark_run_cancelled(
        self,
        run_id: str,
        *,
        books_staged: int = 0,
        books_failed: int = 0,
        message: str = "Auto-run cancelled",
    ) -> None:
        self._update_run(
            run_id,
            status="cancelled",
            phase="cancelled",
            message=message,
            books_staged=books_staged,
            books_failed=books_failed,
            finished=True,
        )

    def _update_run(
        self,
        run_id: str,
        *,
        phase: str | None = None,
        message: str | None = None,
        scan_id: str | None = None,
        books_eligible: int | None = None,
        books_staged: int | None = None,
        books_failed: int | None = None,
        status: str | None = None,
        finished: bool = False,
    ) -> None:
        sets: list[str] = []
        values: list[Any] = []
        if phase is not None:
            sets.append("phase = ?")
            values.append(phase)
        if message is not None:
            sets.append("message = ?")
            values.append(message)
        if scan_id is not None:
            sets.append("scan_id = ?")
            values.append(scan_id)
        if books_eligible is not None:
            sets.append("books_eligible = ?")
            values.append(books_eligible)
        if books_staged is not None:
            sets.append("books_staged = ?")
            values.append(books_staged)
        if books_failed is not None:
            sets.append("books_failed = ?")
            values.append(books_failed)
        if status is not None:
            sets.append("status = ?")
            values.append(status)
        if finished:
            sets.append("finished_at = ?")
            values.append(_utcnow())
        if not sets:
            return
        values.append(run_id)
        with DB_LOCK:
            self.conn.execute(
                f"UPDATE auto_runs SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self.conn.commit()

    def _wait_for_scan(self, scan_id: str, run_id: str) -> bool:
        while True:
            if self._cancel.is_set():
                self._mark_run_cancelled(run_id, message="Auto-run cancelled during scan")
                return False
            with DB_LOCK:
                row = self.conn.execute(
                    "SELECT * FROM scans WHERE id = ?", (scan_id,)
                ).fetchone()
            if not row:
                return False
            if row["status"] == "cancelled":
                self._mark_run_cancelled(run_id, message="Auto-run cancelled during scan")
                return False
            if row["status"] != "running":
                self._update_run(
                    run_id,
                    message=row["message"] or row["status"],
                )
                return row["status"] == "completed"
            msg = row["message"] or "Scanning..."
            total = row["total_books"] or 0
            if total:
                complete = row["books_complete"] or row["metadata_done"] or 0
                msg = f"{msg} ({complete}/{total})"
            self._update_run(run_id, phase="scanning", message=msg)
            time.sleep(1.5)

    def _flatbook_from_row(self, row: sqlite3.Row) -> FlatBook:
        import json

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

    def _compute_conflicts(self) -> tuple[list[dict[str, Any]], set[str]]:
        if self.session is not None:
            self.session.refresh_conflicts(self.conn)
            return self.session.get_conflicts()
        with DB_LOCK:
            rows = self.conn.execute("SELECT * FROM books ORDER BY source_path").fetchall()
        book_dicts = [row_to_book(r) for r in rows]
        persisted = load_conflict_resolutions(self.conn)
        from stager_core.staging import build_inode_index
        from stager_core.conflicts import build_library_index

        return detect_conflict_groups(
            book_dicts,
            self.scan_manager.library_root,
            self.scan_manager.books_root,
            persisted,
            build_library_index(self.scan_manager.library_root),
            build_inode_index(self.scan_manager.library_root),
        )

    def _run_auto(self, run_id: str) -> None:
        books_staged = 0
        books_failed = 0
        try:
            self._update_run(run_id, phase="scanning", message="Starting scan...")
            try:
                scan_id = self.scan_manager.start_scan(auto_run_id=run_id)
            except ScanAlreadyRunning as exc:
                self._update_run(
                    run_id,
                    status="failed",
                    phase="failed",
                    message=str(exc),
                    finished=True,
                )
                return

            self._update_run(run_id, scan_id=scan_id)
            if not self._wait_for_scan(scan_id, run_id):
                with DB_LOCK:
                    scan_row = self.conn.execute(
                        "SELECT message, status FROM scans WHERE id = ?", (scan_id,)
                    ).fetchone()
                if self._cancel.is_set() or (scan_row and scan_row["status"] == "cancelled"):
                    return
                fail_msg = "Scan failed or was interrupted"
                if scan_row and scan_row["message"]:
                    fail_msg = scan_row["message"]
                self._update_run(
                    run_id,
                    status="failed",
                    phase="failed",
                    message=fail_msg,
                    finished=True,
                )
                return

            if get_auto_settings(self.conn)["cache_relookup_pending"]:
                update_auto_settings(self.conn, cache_relookup_pending=False)

            settings = get_auto_settings(self.conn)
            _, conflict_ids = self._compute_conflicts()
            with DB_LOCK:
                rows = self.conn.execute(
                    "SELECT * FROM books WHERE status = 'pending' ORDER BY source_path"
                ).fetchall()
            eligible_rows = []
            for row in rows:
                book = row_to_book(
                    row,
                    in_conflict=row["id"] in conflict_ids,
                )
                if is_eligible_for_auto_stage(
                    book, conflict_ids, settings["min_confidence"]
                ):
                    eligible_rows.append(row)

            self._update_run(
                run_id,
                phase="staging",
                books_eligible=len(eligible_rows),
                message=f"Staging {len(eligible_rows)} eligible book(s)...",
            )

            for idx, row in enumerate(eligible_rows, start=1):
                if self._cancel.is_set():
                    self._mark_run_cancelled(
                        run_id,
                        books_staged=books_staged,
                        books_failed=books_failed,
                    )
                    return
                with DB_LOCK:
                    fresh = self.conn.execute(
                        "SELECT * FROM books WHERE id = ?", (row["id"],)
                    ).fetchone()
                if not fresh or fresh["status"] != "pending":
                    continue
                row = fresh
                book = self._flatbook_from_row(row)
                row_dict = dict(row)
                author, title, series, series_index = resolve_winner_metadata(
                    chosen_author=row_dict.get("chosen_author") or "",
                    chosen_title=row_dict.get("chosen_title") or "",
                    suggested_author=row_dict.get("suggested_author") or "",
                    suggested_title=row_dict.get("suggested_title") or "",
                    flatten_name=row["flatten_name"] or "",
                    chosen_author_set=int(row_dict.get("chosen_author_set") or 0),
                    chosen_title_set=int(row_dict.get("chosen_title_set") or 0),
                    chosen_series=row_dict.get("chosen_series") or "",
                    chosen_series_index=row_dict.get("chosen_series_index") or "",
                    chosen_series_set=int(row_dict.get("chosen_series_set") or 0),
                    chosen_series_index_set=int(row_dict.get("chosen_series_index_set") or 0),
                    suggested_series=row_dict.get("suggested_series") or "",
                    suggested_series_index=row_dict.get("suggested_series_index") or "",
                    suggested_series_state=row_dict.get("suggested_series_state") or "unknown",
                )
                if self.session is not None and self.session.session_ready:
                    inode_index = self.session.get_inode_index_copy()
                else:
                    from stager_core.staging import build_inode_index

                    inode_index = build_inode_index(self.scan_manager.library_root)
                try:
                    result = stage_book_author_title(
                        self.scan_manager.books_root,
                        self.scan_manager.library_root,
                        book,
                        author,
                        title,
                        inode_index,
                        dry_run=False,
                        series=series,
                        series_index=series_index,
                    )
                    if result.status in {"staged", "already_staged"}:
                        staged_now = result.status == "staged"
                        with DB_LOCK:
                            self.conn.execute(
                                """
                                UPDATE books SET
                                    status = 'staged', staged_path = ?, chosen_author = ?,
                                    chosen_title = ?, chosen_series = ?, chosen_series_index = ?,
                                    error = '', updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    result.target_path,
                                    author,
                                    title,
                                    series,
                                    series_index,
                                    _utcnow(),
                                    row["id"],
                                ),
                            )
                            if staged_now:
                                action_id = uuid.uuid4().hex[:12]
                                self.conn.execute(
                                    """
                                    INSERT INTO auto_actions (
                                        id, run_id, book_id, action, author, title, confidence,
                                        staged_path, source_path, created_at, min_confidence
                                    ) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        action_id,
                                        run_id,
                                        row["id"],
                                        author,
                                        title,
                                        row["confidence"],
                                        result.target_path,
                                        row["source_path"],
                                        _utcnow(),
                                        settings["min_confidence"],
                                    ),
                                )
                                books_staged += 1
                            self.conn.commit()
                        if staged_now:
                            insert_decision_outcome(
                                self.conn,
                                book_id=row["id"],
                                action="auto_stage",
                                author=author,
                                title=title,
                                confidence_at_action=float(row["confidence"] or 0),
                            )
                        if self.session is not None:
                            self.session.merge_inode_index(inode_index)
                            self.session.apply_stage(book, result, self.conn)
                            self.session.refresh_conflicts(self.conn)
                    else:
                        books_failed += 1
                        with DB_LOCK:
                            self.conn.execute(
                                "UPDATE books SET error = ?, updated_at = ? WHERE id = ?",
                                (result.error or result.status, _utcnow(), row["id"]),
                            )
                            self.conn.commit()
                except Exception as exc:
                    logger.exception("auto-stage failed for %s", row["id"])
                    books_failed += 1

                self._update_run(
                    run_id,
                    phase="staging",
                    books_staged=books_staged,
                    books_failed=books_failed,
                    message=f"Staging {idx}/{len(eligible_rows)}...",
                )

            finish_msg = f"Auto-run complete: {books_staged} staged"
            if books_failed:
                finish_msg += f", {books_failed} failed"
            self._update_run(
                run_id,
                status="completed",
                phase="completed",
                books_staged=books_staged,
                books_failed=books_failed,
                message=finish_msg,
                finished=True,
            )
        except Exception as exc:
            logger.exception("auto-run %s failed", run_id)
            self._update_run(
                run_id,
                status="failed",
                phase="failed",
                books_staged=books_staged,
                books_failed=books_failed,
                message=str(exc),
                finished=True,
            )


def try_scheduled_tick(auto_manager: AutoRunManager) -> None:
    try:
        auto_manager.start_run(trigger="scheduled", require_enabled=True)
    except (AutoRunAlreadyRunning, AutoRunBlocked):
        return
