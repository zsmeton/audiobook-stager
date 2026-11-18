"""B. Scan discovery + rescan cancel must not wipe books."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import (
    books_snapshot,
    seed_file,
    staging_rows,
    wait_scan_finished,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_layout("happy_scan")]


def test_b_scan_populates_staging(scanned_page, stager_server):
    page = scanned_page
    snap = books_snapshot(stager_server["base_url"])
    assert len(snap) == 3, snap
    titles = {row["effective_title"] for row in snap.values()}
    assert titles == {"Red Rising", "Project Hail Mary", "Golden Son"}, titles

    expect(staging_rows(page)).to_have_count(3, timeout=15_000)
    body = page.locator("#booksList").inner_text()
    assert "Red Rising" in body
    assert "Project Hail Mary" in body
    assert "Golden Son" in body
    expect(page.locator("#stagingCount")).not_to_have_attribute("data-count", "0")


@pytest.mark.e2e_fixture_delay_ms(400)
def test_b_rescan_cancel_keeps_books_and_seeds(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]
    books_root = Path(stager_server["books_root"])

    before = books_snapshot(base)
    assert len(before) == 3, before
    before_ids = set(before)
    for snap in before.values():
        assert snap["status"] == "pending"
        assert seed_file(books_root, snap).is_file()

    expect(staging_rows(page)).to_have_count(3, timeout=15_000)

    page.locator("#scanBtn").click()
    action = page.locator("#bootstrapActionBtn")
    expect(action).to_be_visible(timeout=30_000)
    expect(action).to_contain_text("Start Scan")
    action.click()

    cancel = page.locator("#bootstrapCancelBtn")
    expect(cancel).to_be_visible(timeout=30_000)
    expect(cancel).to_be_enabled(timeout=30_000)
    cancel.click()

    latest = wait_scan_finished(base, allow=("cancelled",))
    assert latest.get("status") == "cancelled"
    expect(page.locator("#bootstrapScrim")).to_be_hidden(timeout=60_000)
    expect(page.locator("#scanBtn")).to_be_enabled(timeout=30_000)

    after = books_snapshot(base)
    assert set(after) == before_ids
    for book_id, snap in before.items():
        assert after[book_id]["status"] == snap["status"]
        assert after[book_id]["in_conflict"] == snap["in_conflict"]
        assert seed_file(books_root, snap).is_file()

    expect(staging_rows(page)).to_have_count(3, timeout=15_000)
    ui_ids = {
        staging_rows(page).nth(i).get_attribute("data-book-id")
        for i in range(staging_rows(page).count())
    }
    assert ui_ids == before_ids
