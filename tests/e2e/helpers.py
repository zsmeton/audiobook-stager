"""Shared helpers for Playwright e2e tests."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterable

import httpx
from playwright.sync_api import Page, expect


def api_get(base_url: str, path: str) -> dict[str, Any]:
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        resp = client.get(path)
        resp.raise_for_status()
        return resp.json()


def wait_scan_finished(
    base_url: str,
    *,
    allow: Iterable[str] = ("completed",),
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Wait until nothing is running and the latest scan is in ``allow``."""
    allowed = set(allow)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        running = api_get(base_url, "/api/scan/running")
        latest = api_get(base_url, "/api/scan/latest")
        running_idle = running.get("status") == "none"
        latest_status = latest.get("status")
        if running_idle and latest_status in allowed:
            return latest
        if running_idle and latest_status in {"completed", "cancelled", "error", "failed"}:
            raise RuntimeError(f"scan finished with status={latest_status}: {latest}")
        time.sleep(0.25)
    raise TimeoutError(
        f"scan still running: running={api_get(base_url, '/api/scan/running')} "
        f"latest={api_get(base_url, '/api/scan/latest')}"
    )


def wait_scan_idle(base_url: str, *, timeout_s: float = 180.0) -> dict[str, Any]:
    """Wait until the latest scan completed successfully."""
    return wait_scan_finished(base_url, allow=("completed",), timeout_s=timeout_s)


def dismiss_bootstrap_and_scan(
    page: Page,
    base_url: str,
    *,
    ui_url: str | None = None,
    timeout_s: float = 180.0,
) -> None:
    """Drive the pre-scan / provider scrim through Start Scan and wait until idle."""
    page.goto((ui_url or base_url) + "/")
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("h1")).to_contain_text("Audiobook Stager", timeout=30_000)

    action = page.locator("#bootstrapActionBtn")
    expect(action).to_be_visible(timeout=60_000)
    expect(action).to_be_enabled(timeout=60_000)
    # Provider probes can take a moment; button is "Start Scan".
    expect(action).to_contain_text("Start Scan", timeout=60_000)
    action.click()

    wait_scan_idle(base_url, timeout_s=timeout_s)
    scrim = page.locator("#bootstrapScrim")
    expect(scrim).to_be_hidden(timeout=60_000)


def same_file(a: Path, b: Path) -> bool:
    sa = a.stat()
    sb = b.stat()
    if hasattr(os, "samestat"):
        return os.path.samestat(sa, sb)
    return sa.st_ino == sb.st_ino and sa.st_dev == sb.st_dev


def assert_samefile(a: Path, b: Path) -> None:
    assert a.is_file(), f"missing file: {a}"
    assert b.is_file(), f"missing file: {b}"
    assert same_file(a, b), f"expected hardlink {a} <-> {b}"


def assert_not_samefile(a: Path, b: Path) -> None:
    if not a.is_file() or not b.is_file():
        return
    assert not same_file(a, b), f"did not expect hardlink {a} <-> {b}"


def list_books(base_url: str, **params: Any) -> dict[str, Any]:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    path = "/api/books"
    if q:
        path = f"{path}?{q}"
    return api_get(base_url, path)


def all_books(base_url: str) -> list[dict[str, Any]]:
    return list(list_books(base_url).get("items") or [])


def books_snapshot(base_url: str) -> dict[str, dict[str, Any]]:
    """id → status / conflict / staged_path / seed relative path."""
    out: dict[str, dict[str, Any]] = {}
    for book in all_books(base_url):
        files = book.get("files") or []
        seed_rel = ""
        if files:
            seed_rel = str(files[0].get("source") or "")
        out[str(book["id"])] = {
            "id": str(book["id"]),
            "status": book.get("status") or "",
            "in_conflict": bool(book.get("in_conflict")),
            "staged_path": book.get("staged_path") or "",
            "source_path": book.get("source_path") or "",
            "seed_rel": seed_rel,
            "effective_title": book.get("effective_title") or "",
            "effective_author": book.get("effective_author") or "",
        }
    return out


def seed_file(books_root: Path, snap: dict[str, Any]) -> Path:
    rel = (snap.get("seed_rel") or "").replace("\\", "/").strip("/")
    assert rel, f"no seed path on {snap}"
    return books_root.joinpath(*rel.split("/"))


def staged_dir(library_root: Path, snap: dict[str, Any]) -> Path:
    rel = (snap.get("staged_path") or "").replace("\\", "/").strip("/")
    assert rel, f"no staged_path on {snap}"
    return library_root.joinpath(*rel.split("/"))


def dest_audio_files(dest: Path) -> list[Path]:
    if not dest.is_dir():
        return []
    return [p for p in dest.iterdir() if p.is_file()]


def pending_staging(base_url: str) -> list[dict[str, Any]]:
    data = list_books(base_url, partitioned="true")
    return [
        b
        for b in (data.get("staging") or [])
        if b.get("status") == "pending" and not b.get("in_conflict")
    ]


def staging_rows(page: Page):
    return page.locator("#booksList .staging-row[data-book-id]")


def conflict_rows(page: Page):
    return page.locator("#conflictsList .group-row[data-target-key]")


def row_ids(locator) -> list[str]:
    return [locator.nth(i).get_attribute("data-book-id") or "" for i in range(locator.count())]


def book_row(page: Page, book_id: str):
    return page.locator(f'#booksList .staging-row[data-book-id="{book_id}"]')


def select_status(page: Page, status: str) -> None:
    page.locator("#statusFilter").select_option(status)
