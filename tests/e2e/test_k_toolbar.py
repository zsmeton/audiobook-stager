"""K. Staging toolbar — filter / search / sort (order must actually change)."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import row_ids, staging_rows

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_layout("happy_scan")]


def test_k_filter_search_sort(scanned_page, stager_server):
    page = scanned_page
    expect(staging_rows(page)).to_have_count(3, timeout=15_000)

    page.locator("#searchBox").fill("Hail Mary")
    expect(staging_rows(page)).to_have_count(1, timeout=10_000)
    expect(page.locator("#booksList")).to_contain_text("Hail Mary")

    page.locator("#searchBox").fill("")
    expect(staging_rows(page)).to_have_count(3, timeout=10_000)

    before = row_ids(staging_rows(page))
    assert len(before) == 3
    page.locator('.book-item__head [data-sort="source_path"] .book-item__sort-btn').click()
    expect(staging_rows(page).first).not_to_have_attribute("data-book-id", before[0], timeout=10_000)
    after = row_ids(staging_rows(page))
    assert after == list(reversed(before)), (before, after)

    first_id = after[0]
    page.locator(f'.book-item[data-book-id="{first_id}"] button[data-action="skip"]').click()
    page.locator("#statusFilter").select_option("skipped")
    expect(staging_rows(page)).to_have_count(1, timeout=10_000)
    expect(staging_rows(page).first).to_have_attribute("data-book-id", first_id)
