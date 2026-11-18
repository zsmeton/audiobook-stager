"""F. Merge split parts — both seeds hardlinked into the dest."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import books_snapshot, conflict_rows, dest_audio_files, same_file, seed_file

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_layout("merge_parts")]


def test_f_merge_and_stage(scanned_page, stager_server):
    page = scanned_page
    books_root = Path(stager_server["books_root"])
    library = Path(stager_server["library_root"])

    before = books_snapshot(stager_server["base_url"])
    assert len(before) == 2, before
    seeds = [seed_file(books_root, snap) for snap in before.values()]
    assert all(p.is_file() for p in seeds), seeds

    expect(conflict_rows(page)).to_have_count(1, timeout=15_000)
    conflict_rows(page).first.locator("button.conflict-resolve-btn").click()

    dialog = page.locator("#conflictDialog")
    expect(dialog).to_be_visible()

    merge_tab = dialog.locator(
        'button[role="tab"][data-resolve-mode="merge"], button.resolve-tab:has-text("Merge")'
    )
    expect(merge_tab.first).to_be_visible(timeout=15_000)
    merge_tab.first.click()

    merge_btn = page.locator("#mergeApproveBtn")
    expect(merge_btn).to_be_visible(timeout=30_000)
    expect(merge_btn).to_be_enabled(timeout=30_000)
    merge_btn.click()

    expect(dialog).to_be_hidden(timeout=90_000)
    expect(conflict_rows(page)).to_have_count(0, timeout=30_000)

    dest = library / "Merge Author" / "Split Book"
    dest_files = dest_audio_files(dest)
    assert dest.is_dir(), list(library.rglob("*"))
    assert len(dest_files) >= 2, dest_files
    for seed in seeds:
        assert seed.is_file()
        assert any(same_file(seed, d) for d in dest_files), (seed, dest_files)
