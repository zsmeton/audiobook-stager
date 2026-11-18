"""H. Library vocabulary chrome after staging a canonical author."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import dismiss_bootstrap_and_scan, list_books, wait_scan_idle

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_layout("lvi")]


def test_h_lvi_gold_chrome_on_detail(scanned_page, stager_server):
    page = scanned_page
    base = stager_server["base_url"]

    staging = list_books(base, partitioned="true").get("staging") or []
    three = next(
        (
            b
            for b in staging
            if "Three-Body" in (b.get("effective_title") or "")
            or "Three-Body" in (b.get("source_path") or "")
        ),
        None,
    )
    assert three, staging
    page.locator(f'.book-item[data-book-id="{three["id"]}"] button[data-action="approve"]').click()
    expect(page.locator(f'.book-item[data-book-id="{three["id"]}"]')).to_be_hidden(timeout=30_000)

    # Rescan so Dark Forest lookup uses LVI built from the staged row.
    page.locator("#scanBtn").click()
    action = page.locator("#bootstrapActionBtn")
    expect(action).to_be_visible(timeout=30_000)
    expect(action).to_contain_text("Start Scan")
    action.click()
    wait_scan_idle(base)
    expect(page.locator("#bootstrapScrim")).to_be_hidden(timeout=60_000)
    page.goto(base + "/")
    page.wait_for_load_state("networkidle")

    staging = list_books(base, partitioned="true").get("staging") or []
    dark = next(
        (
            b
            for b in staging
            if "Dark Forest" in (b.get("effective_title") or "")
            or "Dark Forest" in (b.get("source_path") or "")
        ),
        None,
    )
    assert dark, staging

    page.locator(f'.book-item[data-book-id="{dark["id"]}"] button[data-action="detail"]').click()
    dialog = page.locator("#detailDialog")
    expect(dialog).to_be_visible()
    chrome = dialog.locator(".metadata-field--lvi-match, input.field-lvi-match")
    expect(chrome.first).to_be_visible(timeout=15_000)
