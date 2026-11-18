"""Author-only catalog sweep (Audible + MAM) with local-signal disambiguation."""

from __future__ import annotations

from stager_core.discovery import FlatBook, stem_base
from stager_core.metadata.normalize import normalize_author, normalize_title
from stager_core.metadata.providers import MetadataProviders
from stager_core.metadata.scoring import title_sim
from stager_core.metadata.series_scoring import series_sim
from stager_core.metadata.types import ManualHints, MetadataCandidate, TagInfo

OEUVRE_SOURCE = "author_oeuvre"
_TITLE_SCORE_EPSILON = 1e-6


def _add_probe(probes: list[str], seen: set[str], val: str) -> None:
    v = (val or "").strip()
    key = v.lower()
    if v and key not in seen:
        seen.add(key)
        probes.append(v)


def build_oeuvre_probes(
    book: FlatBook,
    tags: TagInfo,
    context: dict,
    manual: ManualHints | None,
) -> tuple[list[str], list[str]]:
    """Title probes (disambiguation) and series probes (tie-break only)."""
    title_probes: list[str] = []
    series_probes: list[str] = []
    title_seen: set[str] = set()
    series_seen: set[str] = set()

    if manual and (manual.title or "").strip():
        _add_probe(title_probes, title_seen, manual.title)
    else:
        _add_probe(title_probes, title_seen, tags.album)
        _add_probe(title_probes, title_seen, tags.title)
        _add_probe(title_probes, title_seen, context.get("folder_title") or book.flatten_name)
        if book.files:
            stem = stem_base(book.files[0].name.rsplit(".", 1)[0])
            _add_probe(title_probes, title_seen, stem)

    if manual and (manual.series or "").strip():
        _add_probe(series_probes, series_seen, manual.series)
    raw = tags.raw or {}
    _add_probe(series_probes, series_seen, str(raw.get("contentgroup") or ""))
    _add_probe(series_probes, series_seen, str(raw.get("grouping") or ""))
    parts = book.source_path_parts or []
    if len(parts) >= 3:
        for part in parts[1:-1]:
            _add_probe(series_probes, series_seen, part)

    return title_probes, series_probes


def fetch_author_catalog(providers: MetadataProviders, author: str) -> list[MetadataCandidate]:
    """Pool Audible + MAM author-only results, deduped by author/title."""
    author = (author or "").strip()
    if not author:
        return []

    pooled: list[MetadataCandidate] = []
    seen: set[tuple[str, str]] = set()

    for batch in (
        providers.audible_author_catalog(author),
        providers.mam_search("", author, perpage=25),
    ):
        for cand in batch:
            if not (cand.title or "").strip():
                continue
            key = (
                normalize_author(cand.author).lower(),
                normalize_title(cand.title).lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            pooled.append(cand)
    return pooled


def _title_score(cand: MetadataCandidate, title_probes: list[str]) -> float:
    if not title_probes:
        return 0.0
    return max(title_sim(cand.title, probe) for probe in title_probes)


def _series_score(cand: MetadataCandidate, series_probes: list[str]) -> float:
    if not series_probes:
        return 0.0
    scores: list[float] = []
    for probe in series_probes:
        sim = series_sim(cand.series or "", probe)
        if isinstance(sim, bool):
            scores.append(1.0 if sim else 0.0)
        else:
            scores.append(float(sim))
    return max(scores) if scores else 0.0


def pick_oeuvre_match(
    candidates: list[MetadataCandidate],
    title_probes: list[str],
    series_probes: list[str],
) -> MetadataCandidate | None:
    """Pick closest catalog title; series probes break ties."""
    if not candidates or not title_probes:
        return None

    best: MetadataCandidate | None = None
    best_title = -1.0
    best_series = -1.0

    for cand in candidates:
        ts = _title_score(cand, title_probes)
        ss = _series_score(cand, series_probes) if series_probes else 0.0
        if ts > best_title + _TITLE_SCORE_EPSILON:
            best_title = ts
            best_series = ss
            best = cand
        elif abs(ts - best_title) <= _TITLE_SCORE_EPSILON and ss > best_series + _TITLE_SCORE_EPSILON:
            best_series = ss
            best = cand

    return best


def build_author_oeuvre_candidate(
    picked: MetadataCandidate,
    *,
    catalog_size: int,
    match_score: float,
) -> MetadataCandidate:
    origin = picked.source or ""
    raw = dict(picked.raw) if picked.raw else {}
    raw["oeuvre_match_score"] = round(match_score, 4)
    raw["oeuvre_catalog_size"] = catalog_size
    raw["oeuvre_origin"] = origin
    return MetadataCandidate(
        author=picked.author,
        title=picked.title,
        source=OEUVRE_SOURCE,
        confidence=0.0,
        narrator=picked.narrator,
        series=picked.series,
        series_index=picked.series_index,
        subtitle=picked.subtitle,
        asin=picked.asin,
        isbn=picked.isbn,
        language=picked.language,
        publisher=picked.publisher,
        year=picked.year,
        description=picked.description,
        cover_url=picked.cover_url,
        raw=raw,
    )


def author_oeuvre_candidate(
    providers: MetadataProviders,
    book: FlatBook,
    tags: TagInfo,
    context: dict,
    manual: ManualHints | None,
    catalog_cache: dict[str, list[MetadataCandidate]],
) -> MetadataCandidate | None:
    """Fetch author catalog (cached), pick best local match, return oeuvre candidate."""
    author = normalize_author(context.get("author") or "") or (context.get("author") or "")
    if not author.strip():
        return None

    title_probes, series_probes = build_oeuvre_probes(book, tags, context, manual)
    if not title_probes:
        return None

    cache_key = normalize_author(author).lower()
    if cache_key not in catalog_cache:
        catalog_cache[cache_key] = fetch_author_catalog(providers, author)
    catalog = catalog_cache[cache_key]
    if not catalog:
        return None

    picked = pick_oeuvre_match(catalog, title_probes, series_probes)
    if not picked:
        return None

    match_score = _title_score(picked, title_probes)
    return build_author_oeuvre_candidate(
        picked,
        catalog_size=len(catalog),
        match_score=match_score,
    )
