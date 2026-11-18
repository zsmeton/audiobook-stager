from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from stager_core.metadata.provider_registry import list_provider_status, probe_provider


class FakeProviders:
    def __init__(self, responses: dict[str, tuple[str | int, str]] | None = None):
        self.responses = responses or {}

    def probe_connectivity(self, provider_id: str) -> tuple[str | int, str]:
        return self.responses.get(provider_id, (200, "OK"))


class ProviderRegistryTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "GOOGLE_BOOKS_API_KEY": "",
            "STAGER_MAM_ID": "",
            "STAGER_MAM_COOKIE_FILE": r"Z:\__no_stager_mam_cookies__",
        },
        clear=False,
    )
    def test_list_marks_key_gated_providers(self) -> None:
        items = {p["id"]: p for p in list_provider_status()}
        self.assertTrue(items["audnexus"]["enabled"])
        self.assertFalse(items["audnexus"]["requires_key"])
        self.assertTrue(items["google_books"]["requires_key"])
        self.assertFalse(items["google_books"]["configured"])
        self.assertFalse(items["google_books"]["enabled"])
        self.assertTrue(items["mam"]["requires_key"])
        self.assertFalse(items["mam"]["configured"])

    def test_probe_ok_on_200(self) -> None:
        providers = FakeProviders({"audnexus": ("ok", "OK")})
        result = probe_provider(providers, "audnexus")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["http_status"], 200)

    @patch.dict(
        os.environ,
        {
            "GOOGLE_BOOKS_API_KEY": "",
            "STAGER_MAM_ID": "",
            "STAGER_MAM_COOKIE_FILE": r"Z:\__no_stager_mam_cookies__",
        },
        clear=False,
    )
    def test_probe_skips_unconfigured_google(self) -> None:
        providers = FakeProviders()
        result = probe_provider(providers, "google_books")
        self.assertEqual(result["status"], "skipped")
