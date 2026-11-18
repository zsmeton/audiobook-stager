"""Unit checks for the offline fixture metadata backend."""

from __future__ import annotations

import os
import time
import unittest

from stager_core.metadata.fixture_providers import FixtureMetadataProviders


class FixtureProvidersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.providers = FixtureMetadataProviders()

    def test_title_author_hit(self) -> None:
        hits = self.providers.audible_search("Red Rising", "Pierce Brown")
        self.assertTrue(hits)
        self.assertEqual(hits[0].author, "Pierce Brown")
        self.assertEqual(hits[0].title, "Red Rising")

    def test_does_not_cross_match_unrelated_title(self) -> None:
        hits = self.providers.openlibrary_search("Split Book", "Merge Author")
        self.assertTrue(hits)
        self.assertEqual(hits[0].title, "Split Book")
        self.assertFalse(any(h.title == "The Dark Forest" for h in hits))

    def test_probe_ok(self) -> None:
        status, msg = self.providers.probe_connectivity("audnexus")
        self.assertEqual(status, "ok")
        self.assertIn("fixture", msg.lower())

    def test_backend_env_gate(self) -> None:
        from stager_core.metadata.fixture_providers import fixture_backend_enabled

        old = os.environ.get("STAGER_METADATA_BACKEND")
        try:
            os.environ["STAGER_METADATA_BACKEND"] = "fixture"
            self.assertTrue(fixture_backend_enabled())
            os.environ["STAGER_METADATA_BACKEND"] = ""
            self.assertFalse(fixture_backend_enabled())
        finally:
            if old is None:
                os.environ.pop("STAGER_METADATA_BACKEND", None)
            else:
                os.environ["STAGER_METADATA_BACKEND"] = old

    def test_lookup_delay_env(self) -> None:
        old = os.environ.get("STAGER_FIXTURE_LOOKUP_DELAY_MS")
        try:
            os.environ["STAGER_FIXTURE_LOOKUP_DELAY_MS"] = "25"
            started = time.perf_counter()
            self.providers.audible_search("Red Rising", "Pierce Brown")
            self.assertGreaterEqual(time.perf_counter() - started, 0.02)
        finally:
            if old is None:
                os.environ.pop("STAGER_FIXTURE_LOOKUP_DELAY_MS", None)
            else:
                os.environ["STAGER_FIXTURE_LOOKUP_DELAY_MS"] = old


if __name__ == "__main__":
    unittest.main()
