"""Deterministic metadata providers for e2e / offline tests.

Activated when ``STAGER_METADATA_BACKEND=fixture``. Optional catalog path via
``STAGER_METADATA_FIXTURES`` (JSON). No network I/O.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from stager_core.metadata.normalize import normalize_author, normalize_title
from stager_core.metadata.types import MetadataCandidate

DEFAULT_CATALOG: list[dict[str, Any]] = [
    {
        "id": "red-rising",
        "match_titles": ["red rising"],
        "match_authors": ["pierce brown", "brown"],
        "author": "Pierce Brown",
        "title": "Red Rising",
        "series": "Red Rising",
        "series_index": "1",
        "asin": "B00I2VWW5U",
    },
    {
        "id": "golden-son",
        "match_titles": ["golden son"],
        "match_authors": ["pierce brown", "brown"],
        "author": "Pierce Brown",
        "title": "Golden Son",
        "series": "Red Rising",
        "series_index": "2",
        "asin": "B00KQ6X6IO",
    },
    {
        "id": "three-body",
        "match_titles": ["the three-body problem", "three-body problem", "three body problem"],
        "match_authors": ["cixin liu", "liu cixin", "cixin", "liu"],
        "author": "Cixin Liu",
        "title": "The Three-Body Problem",
        "series": "Remembrance of Earth's Past",
        "series_index": "1",
        "asin": "B00P02AOEE",
    },
    {
        "id": "dark-forest",
        "match_titles": ["the dark forest", "dark forest"],
        "match_authors": ["cixin liu", "liu cixin", "cixin", "liu"],
        "author": "Cixin Liu",
        "title": "The Dark Forest",
        "series": "Remembrance of Earth's Past",
        "series_index": "2",
        "asin": "B00R2H0V2G",
    },
    {
        "id": "project-hail-mary",
        "match_titles": ["project hail mary"],
        "match_authors": ["andy weir", "weir"],
        "author": "Andy Weir",
        "title": "Project Hail Mary",
        "series": "",
        "series_index": "",
        "asin": "B08G9PRS1K",
    },
    {
        "id": "split-book",
        "match_titles": ["split book", "split audiobook"],
        "match_authors": ["merge author", "author"],
        "author": "Merge Author",
        "title": "Split Book",
        "series": "",
        "series_index": "",
        "asin": "",
    },
    {
        "id": "conflict-alpha",
        "match_titles": ["shared title"],
        "match_authors": ["conflict author"],
        "author": "Conflict Author",
        "title": "Shared Title",
        "series": "",
        "series_index": "",
        "asin": "",
    },
]


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _title_key(value: str) -> str:
    return _norm(normalize_title(value) or value)


def _author_key(value: str) -> str:
    return _norm(normalize_author(value) or value)


def load_fixture_catalog(path: str | Path | None = None) -> list[dict[str, Any]]:
    raw = path or os.environ.get("STAGER_METADATA_FIXTURES", "").strip()
    if not raw:
        return list(DEFAULT_CATALOG)
    data = json.loads(Path(raw).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        books = data.get("books") or data.get("catalog") or []
    else:
        books = data
    if not isinstance(books, list) or not books:
        raise ValueError(f"fixture catalog empty or invalid: {raw}")
    return list(books)


def fixture_backend_enabled() -> bool:
    return (os.environ.get("STAGER_METADATA_BACKEND") or "").strip().lower() == "fixture"


def fixture_lookup_delay_ms() -> float:
    raw = (os.environ.get("STAGER_FIXTURE_LOOKUP_DELAY_MS") or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def _maybe_lookup_delay() -> None:
    ms = fixture_lookup_delay_ms()
    if ms > 0:
        time.sleep(ms / 1000.0)


class FixtureMetadataProviders:
    """Drop-in stand-in for ``MetadataProviders`` used by lookup + probes."""

    def __init__(self, catalog: list[dict[str, Any]] | None = None):
        self.catalog = catalog if catalog is not None else load_fixture_catalog()
        self.region = "us"
        self.google_api_key = "fixture"
        self.mam_id = "fixture"

    def _entries_for(self, title: str = "", author: str = "") -> list[dict[str, Any]]:
        t = _title_key(title)
        a = _author_key(author)
        hits: list[dict[str, Any]] = []
        for entry in self.catalog:
            titles = [_title_key(x) for x in entry.get("match_titles") or [entry.get("title") or ""]]
            titles = [x for x in titles if x]
            authors = [_author_key(x) for x in entry.get("match_authors") or [entry.get("author") or ""]]
            authors = [x for x in authors if x]
            if t:
                title_ok = any(t == mt or t in mt or mt in t for mt in titles)
            else:
                # Title-only / author-catalog style queries: allow author match alone.
                title_ok = True
            if not title_ok:
                continue
            if a and authors:
                author_ok = any(a == ma or a in ma or ma in a for ma in authors)
                if not author_ok:
                    # Still allow strong title-only hits when author is messy.
                    if not t:
                        continue
            hits.append(entry)
        return hits

    def _to_candidate(self, entry: dict[str, Any], source: str) -> MetadataCandidate:
        return MetadataCandidate(
            author=str(entry.get("author") or ""),
            title=str(entry.get("title") or ""),
            source=source,
            confidence=0.92,
            series=str(entry.get("series") or ""),
            series_index=str(entry.get("series_index") or ""),
            asin=str(entry.get("asin") or ""),
            raw={"fixture_id": entry.get("id") or ""},
        )

    def _search(self, title: str = "", author: str = "", *, source: str) -> list[MetadataCandidate]:
        _maybe_lookup_delay()
        return [self._to_candidate(e, source) for e in self._entries_for(title, author)]

    def audible_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        return self._search(title, author, source="audible")

    def mam_search(self, title: str = "", author: str = "", *, perpage: int = 5) -> list[MetadataCandidate]:
        return self._search(title, author, source="mam")[:perpage]

    def google_books_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        return self._search(title, author, source="google")

    def openlibrary_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        return self._search(title, author, source="openlibrary")

    def audible_search_title_only(self, title: str) -> list[MetadataCandidate]:
        return self._search(title, "", source="audible")

    def mam_search_title_only(self, title: str, *, perpage: int = 5) -> list[MetadataCandidate]:
        return self._search(title, "", source="mam")[:perpage]

    def google_books_search_title_only(self, title: str) -> list[MetadataCandidate]:
        return self._search(title, "", source="google")

    def openlibrary_search_title_only(self, title: str) -> list[MetadataCandidate]:
        return self._search(title, "", source="openlibrary")

    def audnexus_book(self, asin: str) -> list[MetadataCandidate]:
        asin_n = (asin or "").strip().upper()
        if not asin_n:
            return []
        for entry in self.catalog:
            if str(entry.get("asin") or "").strip().upper() == asin_n:
                return [self._to_candidate(entry, "audnexus")]
        return []

    def audible_author_catalog(
        self, author_name: str, *, max_pages: int = 3
    ) -> list[MetadataCandidate]:
        a = _author_key(author_name)
        out: list[MetadataCandidate] = []
        for entry in self.catalog:
            authors = [_author_key(x) for x in entry.get("match_authors") or [entry.get("author") or ""]]
            if any(a and (a == ma or a in ma or ma in a) for ma in authors if ma):
                out.append(self._to_candidate(entry, "audible"))
        return out

    def audnexus_author_verify(self, author_name: str) -> MetadataCandidate | None:
        hits = self.audible_author_catalog(author_name)
        if not hits:
            return None
        return MetadataCandidate(
            author=hits[0].author,
            title="",
            source="audnexus_author",
            confidence=0.0,
        )

    def probe_connectivity(self, provider_id: str) -> tuple[str | int, str]:
        known = {"audnexus", "audible", "openlibrary", "google_books", "mam"}
        if provider_id not in known:
            return 0, "unknown provider"
        return "ok", "OK (fixture)"
