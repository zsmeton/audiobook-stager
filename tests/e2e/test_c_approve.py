"""C. Approve / unstage / skip / bulk — isolated, with sibling + filesystem asserts."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import (
    book_row,
    books_snapshot,
    dest_audio_files,
    pending_staging,
    same_file,
    seed_file,
    select_status,
    staged_dir,
    staging_rows,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_layout("happy_scan")]


def _pending_ids(base: str) -> list[str]:
    return [b["id"] for b in pending_staging(base)]


def _assert_hardlinked(seed: Path, dest: Path) -> None:
    dest_files = dest_audio_files(dest)
    assert dest_files, dest
    assert seed.is_file(), seed
    assert any(same_file(seed, d) for d in dest_files), dest_files


def test_c_approve_hardlinks_seed_and_leaves_siblings(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    library = Path(stager_server["library_root"])
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    pending_ids = _pending_ids(base)
    assert len(pending_ids) == 3, pending_ids
    book_id = pending_ids[0]
    siblings = [i for i in pending_ids if i != book_id]

    row = book_row(page, book_id)
    expect(row).to_be_visible()
    row.locator('button[data-action="approve"]').click()
    expect(row).to_be_hidden(timeout=30_000)

    after = books_snapshot(base)
    assert set(after) == set(before)
    assert after[book_id]["status"] == "staged"
    assert not after[book_id]["in_conflict"]
    for sib in siblings:
        assert after[sib]["status"] == "pending"
        assert not after[sib]["in_conflict"]
        assert seed_file(books_root, before[sib]).is_file()

    _assert_hardlinked(seed_file(books_root, before[book_id]), staged_dir(library, after[book_id]))
    expect(staging_rows(page)).to_have_count(2, timeout=15_000)
    for sib in siblings:
        expect(book_row(page, sib)).to_be_visible()


def test_c_unstage_returns_to_pending_and_removes_dest(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    library = Path(stager_server["library_root"])
    books_root = Path(stager_server["books_root"])

    pending_ids = _pending_ids(base)
    book_id = pending_ids[0]
    siblings = [i for i in pending_ids if i != book_id]
    before = books_snapshot(base)

    row = book_row(page, book_id)
    expect(row).to_be_visible()
    row.locator('button[data-action="approve"]').click()
    expect(row).to_be_hidden(timeout=30_000)

    staged = books_snapshot(base)[book_id]
    dest = staged_dir(library, staged)
    seed = seed_file(books_root, before[book_id])
    _assert_hardlinked(seed, dest)

    select_status(page, "staged")
    staged_row = book_row(page, book_id)
    expect(staged_row).to_be_visible(timeout=15_000)
    staged_row.locator('button[data-action="unstage"]').click()
    confirm_ok = page.locator("#confirmOkBtn")
    expect(confirm_ok).to_be_visible(timeout=10_000)
    confirm_ok.click()
    expect(book_row(page, book_id)).to_have_count(0, timeout=30_000)

    after = books_snapshot(base)
    assert set(after) == set(before)
    assert after[book_id]["status"] == "pending"
    assert not after[book_id]["in_conflict"]
    assert seed.is_file()
    assert not dest.exists() or not dest_audio_files(dest)
    for sib in siblings:
        assert after[sib]["status"] == before[sib]["status"]
        assert seed_file(books_root, before[sib]).is_file()

    select_status(page, "pending")
    expect(book_row(page, book_id)).to_be_visible(timeout=15_000)


def test_c_skip_and_unskip_does_not_write_library(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    library = Path(stager_server["library_root"])
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    pending_ids = _pending_ids(base)
    book_id = pending_ids[0]
    siblings = [i for i in pending_ids if i != book_id]
    lib_before = {p for p in library.rglob("*") if p.is_file()}

    row = book_row(page, book_id)
    expect(row).to_be_visible()
    row.locator('button[data-action="skip"]').click()
    expect(row).to_be_hidden(timeout=15_000)

    skipped = books_snapshot(base)
    assert skipped[book_id]["status"] == "skipped"
    for sib in siblings:
        assert skipped[sib]["status"] == "pending"
        expect(book_row(page, sib)).to_be_visible()
    assert seed_file(books_root, before[book_id]).is_file()
    assert {p for p in library.rglob("*") if p.is_file()} == lib_before

    select_status(page, "skipped")
    skipped_row = book_row(page, book_id)
    expect(skipped_row).to_be_visible(timeout=15_000)
    skipped_row.locator('button[data-action="unskip"]').click()
    expect(skipped_row).to_be_hidden(timeout=15_000)

    after = books_snapshot(base)
    assert after[book_id]["status"] == "pending"
    assert not after[book_id]["in_conflict"]
    select_status(page, "pending")
    expect(book_row(page, book_id)).to_be_visible(timeout=15_000)
    assert {p for p in library.rglob("*") if p.is_file()} == lib_before


def test_c_bulk_approve_hardlinks_remaining(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    library = Path(stager_server["library_root"])
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    pending_ids = _pending_ids(base)
    assert len(pending_ids) == 3, pending_ids

    expect(staging_rows(page)).to_have_count(3, timeout=15_000)
    checks = page.locator("#booksList .row-check:not([disabled])")
    expect(checks).to_have_count(3)
    for i in range(checks.count()):
        checks.nth(i).check()
    page.locator("#stagingBulkBtn").click()
    expect(staging_rows(page)).to_have_count(0, timeout=60_000)

    after = books_snapshot(base)
    assert set(after) == set(before)
    for book_id in pending_ids:
        assert after[book_id]["status"] == "staged"
        _assert_hardlinked(
            seed_file(books_root, before[book_id]),
            staged_dir(library, after[book_id]),
        )
