from __future__ import annotations

import unittest

from stager_core.metadata.lookup import MetadataLookupService
from stager_core.metadata.normalize import is_generic_title
from stager_core.metadata.providers import MetadataProviders
from stager_core.metadata.scoring import (
    Evidence,
    LOCAL_ONLY_CAP,
    pick_winner,
    source_prior,
)
from stager_core.metadata.types import MetadataCandidate


def cand(source: str, author: str, title: str) -> MetadataCandidate:
    return MetadataCandidate(author=author, title=title, source=source, confidence=0.0)


class RecordingSearch:
    """A stand-in provider search fn that records (title, author) calls."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str = "", author: str = ""):
        self.calls.append((title, author))
        return self.responder(title, author)


class FakeProviders:
    def __init__(self, *, audible=None, mam=None, google=None, openlibrary=None):
        empty = RecordingSearch(lambda t, a: [])
        self.audible_search = audible or empty
        self.mam_search = mam or RecordingSearch(lambda t, a: [])
        self.google_books_search = google or RecordingSearch(lambda t, a: [])
        self.openlibrary_search = openlibrary or RecordingSearch(lambda t, a: [])


def _service_with(providers) -> MetadataLookupService:
    svc = MetadataLookupService.__new__(MetadataLookupService)
    svc.providers = providers
    return svc


class GenericTitleTests(unittest.TestCase):
    def test_flags_structural_and_short_titles(self) -> None:
        for junk in ["Intro", "Outro", "Chapter 3", "Track 01", "01", "001", "1 - 2", "ch", "A"]:
            self.assertTrue(is_generic_title(junk), junk)

    def test_keeps_real_titles(self) -> None:
        for good in ["The Six", "Red Rising", "Dune", "Project Hail Mary"]:
            self.assertFalse(is_generic_title(good), good)


class MultiPassOrchestrationTests(unittest.TestCase):
    def test_combined_only_no_inline_title_fallback(self) -> None:
        ol = RecordingSearch(
            lambda t, a: [cand("openlibrary", "Loren Grush", "The Six")] if (t and not a) else []
        )
        svc = _service_with(FakeProviders(openlibrary=ol))

        pooled = svc._external_candidates("The Six", "Loren Grush_Ines del Castillo")

        # Combined miss: no inline title-only fallback (title-first pass handles that).
        self.assertEqual(pooled, [])
        self.assertEqual(ol.calls, [("The Six", "Loren Grush_Ines del Castillo")])

    def test_combined_hit_skips_fallback(self) -> None:
        ol = RecordingSearch(
            lambda t, a: [cand("openlibrary", "Loren Grush", "The Six")] if (t and a) else []
        )
        svc = _service_with(FakeProviders(openlibrary=ol))

        pooled = svc._external_candidates("The Six", "Loren Grush")

        self.assertEqual(len(pooled), 1)
        # Only the combined pass ran.
        self.assertEqual(ol.calls, [("The Six", "Loren Grush")])

    def test_dedupe_across_providers(self) -> None:
        """Title-first dedupes identical author/title across provider batches."""
        from stager_core.metadata.title_first import fetch_title_first_candidates

        dup = cand("openlibrary", "Real Author", "Some Title")

        class DupProviders:
            def audible_search_title_only(self, title: str):
                return [dup]

            def mam_search_title_only(self, title: str, *, perpage: int = 5):
                return [dup]

            def google_books_search_title_only(self, title: str):
                return []

            def openlibrary_search_title_only(self, title: str):
                return []

        pooled = fetch_title_first_candidates(DupProviders(), "Some Title")
        self.assertEqual(len(pooled), 1)

    def test_junk_title_skips_title_only_pass(self) -> None:
        ol = RecordingSearch(lambda t, a: [])
        svc = _service_with(FakeProviders(openlibrary=ol))

        svc._external_candidates("Chapter 3", "Real Author")

        # combined only; no title-only fallback for a junk title.
        self.assertEqual(ol.calls, [("Chapter 3", "Real Author")])

    def test_empty_author_combined_is_title_only_query(self) -> None:
        ol = RecordingSearch(
            lambda t, a: [cand("openlibrary", "Loren Grush", "The Six")] if (t and not a) else []
        )
        svc = _service_with(FakeProviders(openlibrary=ol))

        pooled = svc._external_candidates("The Six", "")

        self.assertEqual(len(pooled), 1)
        self.assertEqual(ol.calls, [("The Six", "")])


class FakeCache:
    def get(self, provider, cache_key):
        return None

    def put(self, *args, **kwargs):
        return None

    def put_permanent(self, *args, **kwargs):
        return None


class TheSixClient:
    """Mocked HTTP client: OpenLibrary only matches a *title-only* "The Six"."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def request_json(self, provider, url, *, method="GET", data=None, headers=None, max_attempts=4):
        self.calls.append((provider, url))
        if provider == "openlibrary" and "author=" not in url and "title=The+Six" in url:
            return (
                200,
                {
                    "docs": [
                        {
                            "title": "The Six",
                            "author_name": ["Loren Grush"],
                            "first_publish_year": 2025,
                        }
                    ]
                },
                {},
            )
        if provider == "openlibrary":
            return (200, {"docs": []}, {})
        return (0, None, {})


class TheSixRegressionTests(unittest.TestCase):
    """End-to-end-ish: the production miss now resolves via the title-only pass."""

    TITLE = "The Six"
    # Garbled combined author the way the search context carried it.
    AUTHOR = "Loren Grush/Ines del Castillo"

    def _local_evidence(self) -> list[Evidence]:
        locals_ = [
            cand("id3", self.AUTHOR, self.TITLE),
            cand("folder", self.AUTHOR, self.TITLE),
            cand("filename", "", self.TITLE),
        ]
        return [
            Evidence(
                source=c.source,
                author=c.author,
                title=c.title,
                weight=source_prior(c.source),
                extras={"candidate": c},
            )
            for c in locals_
        ]

    def test_local_only_is_capped(self) -> None:
        # Baseline: with no external candidate, confidence is capped at 0.65.
        _, breakdown = pick_winner(self._local_evidence())
        self.assertLessEqual(breakdown["confidence"], LOCAL_ONLY_CAP)

    def test_title_only_pass_lifts_confidence(self) -> None:
        client = TheSixClient()
        providers = MetadataProviders(client, FakeCache())  # no google key / mam id
        svc = _service_with(providers)
        svc._title_first_cache = {}

        pooled = svc._title_first_candidates(self.TITLE)

        # The real book surfaced via the parallel title-first pass.
        self.assertTrue(
            any(c.source == "title_first" and c.title == "The Six" for c in pooled)
        )

        evidence = [
            Evidence(
                source=c.source,
                author=c.author,
                title=c.title,
                weight=source_prior(c.source),
                extras={"candidate": c},
            )
            for c in pooled
        ] + self._local_evidence()

        winner, breakdown = pick_winner(evidence)
        self.assertIsNotNone(winner)
        self.assertEqual(winner.title, "The Six")
        self.assertIn("title_first", breakdown["families"])
        # External corroboration breaks the local-only cap.
        self.assertGreater(breakdown["confidence"], LOCAL_ONLY_CAP)
        # The external candidate is recoverable from the decision log pool.
        self.assertTrue(
            any(e["source"] == "title_first" for e in breakdown["evidence_pool"])
        )


class ProviderSingleFieldTests(unittest.TestCase):
    def test_openlibrary_author_only_omits_title_param(self) -> None:
        client = TheSixClient()
        providers = MetadataProviders(client, FakeCache())
        providers.openlibrary_search("", "Loren Grush")
        url = client.calls[-1][1]
        self.assertIn("author=Loren+Grush", url)
        self.assertNotIn("title=", url)

    def test_openlibrary_title_only_omits_author_param(self) -> None:
        client = TheSixClient()
        providers = MetadataProviders(client, FakeCache())
        providers.openlibrary_search("The Six", "")
        url = client.calls[-1][1]
        self.assertIn("title=The+Six", url)
        self.assertNotIn("author=", url)

    def test_openlibrary_both_empty_returns_without_request(self) -> None:
        client = TheSixClient()
        providers = MetadataProviders(client, FakeCache())
        self.assertEqual(providers.openlibrary_search("", ""), [])
        self.assertEqual(client.calls, [])

    def test_google_skips_when_no_query_fields(self) -> None:
        client = TheSixClient()
        providers = MetadataProviders(client, FakeCache(), google_api_key="k")
        self.assertEqual(providers.google_books_search("", ""), [])
        self.assertEqual(client.calls, [])

    def test_mam_author_only_text(self) -> None:
        captured = {}

        class MamClient:
            def request_json(
                self, provider, url, *, method="GET", data=None, json_body=None, headers=None, max_attempts=4
            ):
                captured["json_body"] = json_body
                return (200, {"data": []}, {})

        providers = MetadataProviders(MamClient(), FakeCache(), mam_id="abc")
        providers.mam_search("", "Loren Grush")
        body = captured["json_body"]
        self.assertEqual(body["tor"]["text"], "Loren Grush")
        self.assertEqual(body["tor"]["srchIn"], ["author"])


if __name__ == "__main__":
    unittest.main()
