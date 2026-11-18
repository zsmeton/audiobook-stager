"""Title-only provider search with first-hit-per-provider candidates."""

from __future__ import annotations

from stager_core.metadata.normalize import is_generic_title, normalize_author, normalize_title
from stager_core.metadata.providers import MetadataProviders
from stager_core.metadata.types import MetadataCandidate

TITLE_FIRST_SOURCE = "title_first"


def fetch_title_first_candidates(
    providers: MetadataProviders,
    title: str,
) -> list[MetadataCandidate]:
    """One first-hit candidate per provider; source retagged title_first."""
    title = (title or "").strip()
    if not title or is_generic_title(title):
        return []

    pooled: list[MetadataCandidate] = []
    seen: set[tuple[str, str]] = set()

    searches = (
        providers.audible_search_title_only,
        providers.mam_search_title_only,
        providers.openlibrary_search_title_only,
        providers.google_books_search_title_only,
    )
    for search in searches:
        try:
            batch = search(title)
        except Exception:
            continue
        if not batch:
            continue
        cand = batch[0]
        if not (cand.title or "").strip():
            continue
        key = (
            normalize_author(cand.author).lower(),
            normalize_title(cand.title).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        origin = cand.source or ""
        raw = dict(cand.raw) if cand.raw else {}
        raw["title_first_origin"] = origin
        pooled.append(
            MetadataCandidate(
                author=cand.author,
                title=cand.title,
                source=TITLE_FIRST_SOURCE,
                confidence=0.0,
                narrator=cand.narrator,
                series=cand.series,
                series_index=cand.series_index,
                subtitle=cand.subtitle,
                asin=cand.asin,
                isbn=cand.isbn,
                language=cand.language,
                publisher=cand.publisher,
                year=cand.year,
                description=cand.description,
                cover_url=cand.cover_url,
                raw=raw,
            )
        )
    return pooled


def title_first_candidates(
    providers: MetadataProviders,
    title: str,
    *,
    title_cache: dict[str, list[MetadataCandidate]] | None = None,
) -> list[MetadataCandidate]:
    """Fetch title-first hits, optionally cached by normalized title."""
    title = (title or "").strip()
    if not title or is_generic_title(title):
        return []
    cache_key = normalize_title(title).lower()
    if title_cache is not None:
        if cache_key not in title_cache:
            title_cache[cache_key] = fetch_title_first_candidates(providers, title)
        return list(title_cache[cache_key])
    return fetch_title_first_candidates(providers, title)
