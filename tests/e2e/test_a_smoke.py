"""A. Harness smoke — empty roots, page loads, empty scan."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import api_get, dismiss_bootstrap_and_scan

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_layout("smoke")]


def test_a_page_loads_and_empty_scan(page, stager_server):
    base = stager_server["base_url"]
    health = api_get(base, "/api/health")
    assert health.get("status") in {"ok", "degraded"}

    dismiss_bootstrap_and_scan(page, base, ui_url=stager_server["ui_url"])

    # Stay on the post-scan page (empty library → needs_scan again on reload).
    expect(page.locator("h1")).to_contain_text("Audiobook Stager")
    expect(page.locator("#stagingEmpty")).to_be_visible()
    expect(page.locator("#stagingEmpty")).to_contain_text("All books staged")
    expect(page.locator("#conflictsEmpty")).to_contain_text("No conflicts")
