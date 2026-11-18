"""Tests for production title-first lookup integration."""

from __future__ import annotations

import unittest

from stager_core.metadata.lookup import MetadataLookupService
from stager_core.metadata.scoring import source_prior
from stager_core.metadata.title_first import TITLE_FIRST_SOURCE, title_first_candidates
from stager_core.metadata.types import MetadataCandidate


def cand(source: str, author: str, title: str) -> MetadataCandidate:
    return MetadataCandidate(author=author, title=title, source=source, confidence=0.0)


class FakeProviders:
    def __init__(self) -> None:
        self.calls = 0

    def audible_search_title_only(self, title: str):
        self.calls += 1
        return [cand("audible", "Real Author", title)]

    def mam_search_title_only(self, title: str, *, perpage: int = 5):
        return []

    def google_books_search_title_only(self, title: str):
        return []

    def openlibrary_search_title_only(self, title: str):
        return []


class TitleFirstProductionTests(unittest.TestCase):
    def test_fetch_title_first_retags_source(self) -> None:
        providers = FakeProviders()
        results = title_first_candidates(providers, "Red Rising")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, TITLE_FIRST_SOURCE)
        self.assertEqual(results[0].author, "Real Author")

    def test_title_first_prior_configured(self) -> None:
        self.assertEqual(source_prior(TITLE_FIRST_SOURCE), 0.75)

    def test_skips_generic_title(self) -> None:
        providers = FakeProviders()
        self.assertEqual(title_first_candidates(providers, "Chapter 3"), [])
        self.assertEqual(providers.calls, 0)

    def test_lookup_includes_title_first_candidates(self) -> None:
        svc = MetadataLookupService.__new__(MetadataLookupService)
        svc.providers = FakeProviders()
        svc._title_first_cache = {}
        results = svc._title_first_candidates("Red Rising")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, TITLE_FIRST_SOURCE)


if __name__ == "__main__":
    unittest.main()
