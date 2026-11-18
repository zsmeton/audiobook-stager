"""E. Conflicts — pick non-suggested winner, edit-Save leave, keep library."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import (
    book_row,
    books_snapshot,
    conflict_rows,
    dest_audio_files,
    same_file,
    seed_file,
    select_status,
    staging_rows,
)

pytestmark = pytest.mark.e2e


def _open_conflict(page):
    expect(conflict_rows(page)).to_have_count(1, timeout=15_000)
    conflict_rows(page).first.locator("button.conflict-resolve-btn").click()
    dialog = page.locator("#conflictDialog")
    expect(dialog).to_be_visible()
    return dialog


def _seed_radios(dialog):
    return dialog.locator('input[type="radio"][name^="conflict-winner-"]:not([value="library"])')


@pytest.mark.e2e_layout("conflict_pending")
def test_e_pick_non_suggested_winner_hardlinks_that_seed(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    library = Path(stager_server["library_root"])
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    assert len(before) == 2, before
    seed_ids = list(before)
    for snap in before.values():
        assert snap["in_conflict"]
        assert seed_file(books_root, snap).is_file()

    dialog = _open_conflict(page)
    radios = _seed_radios(dialog)
    expect(radios).to_have_count(2)

    default_id = None
    for i in range(radios.count()):
        if radios.nth(i).is_checked():
            default_id = radios.nth(i).get_attribute("value")
            break
    if not default_id:
        default_id = radios.first.get_attribute("value")
    other = None
    winner_id = None
    for i in range(radios.count()):
        value = radios.nth(i).get_attribute("value")
        if value and value != default_id:
            other = radios.nth(i)
            winner_id = value
            break
    assert other is not None and winner_id
    loser_id = next(i for i in seed_ids if i != winner_id)
    assert winner_id != default_id

    other.check()
    page.locator("#conflictApproveBtn").click()
    expect(dialog).to_be_hidden(timeout=60_000)
    expect(conflict_rows(page)).to_have_count(0, timeout=30_000)

    after = books_snapshot(base)
    assert set(after) == set(before)
    assert after[winner_id]["status"] == "staged"
    assert after[loser_id]["status"] == "skipped"
    assert not after[winner_id]["in_conflict"]
    assert not after[loser_id]["in_conflict"]

    dest = library / "Conflict Author" / "Shared Title"
    dest_files = dest_audio_files(dest)
    winner_seed = seed_file(books_root, before[winner_id])
    loser_seed = seed_file(books_root, before[loser_id])
    assert winner_seed.is_file()
    assert loser_seed.is_file()
    assert dest_files, list(library.rglob("*"))
    assert any(same_file(winner_seed, d) for d in dest_files), dest_files
    assert not any(same_file(loser_seed, d) for d in dest_files), dest_files


@pytest.mark.e2e_layout("conflict_pending")
def test_e_edit_title_save_leaves_conflict(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    assert len(before) == 2
    ids = list(before)

    dialog = _open_conflict(page)
    title_input = dialog.locator(".conflict-title").first
    expect(title_input).to_be_visible()
    edited_id = title_input.get_attribute("data-book-id")
    assert edited_id
    other_id = next(i for i in ids if i != edited_id)

    title_input.fill("Shared Title Edited")
    save_btn = dialog.locator(f'.conflict-save[data-book-id="{edited_id}"]')
    expect(save_btn).to_be_visible()
    save_btn.click()

    expect(conflict_rows(page)).to_have_count(0, timeout=30_000)

    after = books_snapshot(base)
    assert set(after) == set(before)
    assert after[edited_id]["status"] == "pending"
    assert after[other_id]["status"] == "pending"
    assert not after[edited_id]["in_conflict"]
    assert not after[other_id]["in_conflict"]
    assert "Edited" in after[edited_id]["effective_title"]
    assert seed_file(books_root, before[edited_id]).is_file()
    assert seed_file(books_root, before[other_id]).is_file()

    select_status(page, "pending")
    expect(staging_rows(page)).to_have_count(2, timeout=15_000)
    expect(book_row(page, edited_id)).to_be_visible()
    expect(book_row(page, other_id)).to_be_visible()


@pytest.mark.e2e_layout("conflict_staged")
def test_e_staged_conflict_keep_library(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    library = Path(stager_server["library_root"])
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    incoming = next(iter(before.values()))
    incoming_seed = seed_file(books_root, incoming)
    existing = library / "Conflict Author" / "Shared Title" / "existing.mp3"
    assert existing.is_file()
    existing_stat = existing.stat()

    dialog = _open_conflict(page)
    lib_radio = dialog.locator('input[type="radio"][value="library"]')
    expect(lib_radio).to_be_visible()
    lib_radio.check()

    page.locator("#conflictApproveBtn").click()
    expect(dialog).to_be_hidden(timeout=60_000)

    after = books_snapshot(base)
    assert after[incoming["id"]]["status"] == "skipped"
    assert incoming_seed.is_file()
    assert existing.is_file()
    assert existing.stat().st_ino == existing_stat.st_ino
    assert existing.stat().st_dev == existing_stat.st_dev
    dest_files = dest_audio_files(existing.parent)
    assert not any(same_file(incoming_seed, d) for d in dest_files)
    assert existing.name in {p.name for p in dest_files}
