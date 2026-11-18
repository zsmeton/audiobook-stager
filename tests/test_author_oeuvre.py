"""Tests for author oeuvre lookup (production)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.author_oeuvre import (
    OEUVRE_SOURCE,
    author_oeuvre_candidate,
    build_oeuvre_probes,
    fetch_author_catalog,
    pick_oeuvre_match,
)
from stager_core.metadata.lookup import MetadataLookupService
from stager_core.metadata.query import build_search_context
from stager_core.metadata.scoring import LOCAL_ONLY_CAP, pick_winner, source_prior, Evidence
from stager_core.metadata.types import ManualHints, MetadataCandidate, TagInfo


def _book(
    *,
    flatten_name: str = "02 - The Dark Forest",
    source_path_parts: list[str] | None = None,
    filename: str = "02 - The Dark Forest.m4b",
) -> FlatBook:
    parts = source_path_parts or ["Cixin Liu", "Remembrance of Earth's Past", "02 - The Dark Forest"]
    return FlatBook(
        id="b1",
        flatten_name=flatten_name,
        source_path="/".join(parts),
        source_path_parts=parts,
        top_level_pack=parts[0],
        parent_context=parts[-2] if len(parts) >= 2 else "",
        grouping="folder",
        files=[AudioFile(name=filename, source="/".join(parts + [filename]), size_bytes=1)],
        flatten_target=flatten_name,
    )


def _cand(
    source: str,
    author: str,
    title: str,
    *,
    series: str = "",
) -> MetadataCandidate:
    return MetadataCandidate(
        author=author,
        title=title,
        source=source,
        confidence=0.0,
        series=series,
    )


class OeuvreProbeTests(unittest.TestCase):
    def test_manual_title_is_priority_probe(self) -> None:
        book = _book(filename="misleading.m4b")
        tags = TagInfo(album="Wrong Album", title="Wrong Title")
        context = build_search_context(book, tags, ManualHints(title="The Dark Forest"))
        title_probes, _ = build_oeuvre_probes(book, tags, context, ManualHints(title="The Dark Forest"))
        self.assertEqual(title_probes, ["The Dark Forest"])

    def test_local_probes_when_no_manual(self) -> None:
        book = _book()
        tags = TagInfo(album="Album Probe", title="Title Probe")
        context = build_search_context(book, tags)
        title_probes, series_probes = build_oeuvre_probes(book, tags, context, None)
        self.assertIn("Album Probe", title_probes)
        self.assertIn("Title Probe", title_probes)
        self.assertIn("02 - The Dark Forest", title_probes)
        self.assertIn("Remembrance of Earth's Past", series_probes)


class OeuvrePickTests(unittest.TestCase):
    def test_picks_best_title_match(self) -> None:
        cands = [
            _cand("audible", "Cixin Liu", "The Three-Body Problem"),
            _cand("audible", "Cixin Liu", "The Dark Forest"),
        ]
        picked = pick_oeuvre_match(cands, ["02 - The Dark Forest"], [])
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked.title, "The Dark Forest")

    def test_series_tie_break(self) -> None:
        cands = [
            _cand("audible", "Author", "Book One", series="Other Series"),
            _cand("mam", "Author", "Book One", series="Stormlight Archive"),
        ]
        picked = pick_oeuvre_match(
            cands,
            ["Book One"],
            ["The Stormlight Archive"],
        )
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked.series, "Stormlight Archive")

    def test_skips_without_title_probes(self) -> None:
        self.assertIsNone(pick_oeuvre_match([_cand("audible", "A", "T")], [], []))


class FakeProviders:
    def __init__(self) -> None:
        self.audible_calls = 0
        self.mam_calls = 0
        self._audible_catalog = [
            _cand("audible", "Cixin Liu", "The Three-Body Problem"),
            _cand("audible", "Cixin Liu", "The Dark Forest"),
        ]
        self._mam_catalog = [
            _cand("mam", "Cixin Liu", "The Dark Forest"),
        ]

    def audible_author_catalog(self, author: str, *, num_results: int = 10):
        self.audible_calls += 1
        return list(self._audible_catalog)

    def mam_search(self, title: str = "", author: str = "", *, perpage: int = 5):
        self.mam_calls += 1
        return list(self._mam_catalog)


class OeuvreFetchAndCacheTests(unittest.TestCase):
    def test_fetch_dedupes_across_providers(self) -> None:
        providers = FakeProviders()
        pooled = fetch_author_catalog(providers, "Cixin Liu")
        titles = {c.title for c in pooled}
        self.assertEqual(titles, {"The Three-Body Problem", "The Dark Forest"})
        self.assertEqual(providers.audible_calls, 1)
        self.assertEqual(providers.mam_calls, 1)

    def test_catalog_cache_reuses_author_sweep(self) -> None:
        providers = FakeProviders()
        cache: dict[str, list[MetadataCandidate]] = {}
        book = _book()
        tags = TagInfo()
        context = build_search_context(book, tags)

        first = author_oeuvre_candidate(providers, book, tags, context, None, cache)
        second = author_oeuvre_candidate(providers, book, tags, context, None, cache)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.title, "The Dark Forest")
        self.assertEqual(second.source, OEUVRE_SOURCE)
        self.assertEqual(providers.audible_calls, 1)
        self.assertEqual(providers.mam_calls, 1)

    def test_skips_without_author(self) -> None:
        providers = FakeProviders()
        cache: dict[str, list[MetadataCandidate]] = {}
        book = _book()
        result = author_oeuvre_candidate(
            providers,
            book,
            TagInfo(),
            {"author": "", "folder_title": book.flatten_name},
            None,
            cache,
        )
        self.assertIsNone(result)
        self.assertEqual(providers.audible_calls, 0)


class LookupIntegrationTests(unittest.TestCase):
    def _service_with(self, providers: FakeProviders) -> MetadataLookupService:
        svc = MetadataLookupService.__new__(MetadataLookupService)
        svc.providers = providers
        svc._author_catalog_cache = {}
        svc._title_first_cache = {}
        return svc

    def test_resolve_injects_author_oeuvre_candidate(self) -> None:
        providers = FakeProviders()
        svc = self._service_with(providers)
        book = _book()
        tags = TagInfo(album="02 - The Dark Forest")

        with patch(
            "stager_core.metadata.lookup.read_book_tags",
            return_value=tags,
        ), patch.object(
            svc,
            "_external_candidates",
            return_value=[],
        ), patch.object(
            svc,
            "_local_candidates",
            return_value=[_cand("folder", "Cixin Liu", "02 - The Dark Forest")],
        ), patch.object(svc, "_title_first_candidates", return_value=[]):
            with tempfile.TemporaryDirectory() as tmp:
                resolution = svc._resolve_book_locked(Path(tmp), book, None)

        oeuvre = [c for c in resolution.candidates if c.source == OEUVRE_SOURCE]
        self.assertEqual(len(oeuvre), 1)
        self.assertEqual(oeuvre[0].title, "The Dark Forest")
        self.assertEqual(oeuvre[0].raw.get("oeuvre_origin"), "audible")

    def test_oeuvre_breaks_local_only_cap_with_folder_agreement(self) -> None:
        providers = FakeProviders()
        svc = self._service_with(providers)
        book = _book()
        tags = TagInfo(album="02 - The Dark Forest")
        local = [_cand("folder", "Cixin Liu", "02 - The Dark Forest")]

        with patch(
            "stager_core.metadata.lookup.read_book_tags",
            return_value=tags,
        ), patch.object(svc, "_external_candidates", return_value=[]), patch.object(
            svc, "_local_candidates", return_value=local
        ), patch.object(svc, "_title_first_candidates", return_value=[]):
            with tempfile.TemporaryDirectory() as tmp:
                resolution = svc._resolve_book_locked(Path(tmp), book, None)

        evidence = [
            Evidence(
                source=c.source,
                author=c.author,
                title=c.title,
                weight=source_prior(c.source),
                extras={"candidate": c},
            )
            for c in resolution.candidates
        ]
        _, breakdown = pick_winner(evidence)
        self.assertIn(OEUVRE_SOURCE, breakdown.get("families", {}))
        self.assertGreater(breakdown["confidence"], LOCAL_ONLY_CAP)


if __name__ == "__main__":
    unittest.main()
