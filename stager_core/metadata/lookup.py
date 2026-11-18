from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from stager_core.discovery import FlatBook, stem_base
from stager_core.metadata.author_oeuvre import author_oeuvre_candidate
from stager_core.metadata.cache import ApiCache
from stager_core.metadata.library_vocab import LibraryVocabulary
from stager_core.metadata.lvi import (
    annotate_candidates_lvi,
    apply_lvi_search,
    candidate_sort_lvi_tier,
    library_corroboration_evidence,
    lvi_series_vote,
    resolve_lvi_match,
)
from stager_core.metadata.normalize import (
    is_generic_title,
    normalize_author,
    normalize_title,
)
from stager_core.metadata.provider_registry import list_provider_status, test_all_providers
from stager_core.metadata.providers import (
    MetadataProviders,
    persist_stager_mam_cookie,
    resolve_mam_id,
    stager_mam_cookie_path,
)
from stager_core.metadata.query import build_search_context
from stager_core.metadata.title_extraction import TitleExtractionConfig, extract_title
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.scoring import Evidence, pick_winner, source_prior
from stager_core.metadata.effective import primary_candidate_series_from_candidates
from stager_core.metadata.series_scoring import (
    annotate_series_membership,
    fold_staging_confidence,
    id3_series_vote,
    pick_series,
    pick_series_votes_from_cluster,
)
from stager_core.metadata.tags import read_book_tags, tag_candidate
from stager_core.metadata.title_first import title_first_candidates
from stager_core.metadata.types import ManualHints, MetadataCandidate, TagInfo


@dataclass
class LviLookupOptions:
    lvi: LibraryVocabulary | None = None
    lvi_search: bool = True
    lvi_boost: bool = True
    title_extraction: TitleExtractionConfig | None = None


@dataclass
class LookupResolution:
    candidates: list[MetadataCandidate]
    tags: TagInfo
    suggested_author: str
    suggested_title: str
    suggested_series: str
    suggested_series_index: str
    suggested_series_state: str
    suggested_series_source: str
    confidence: float
    confidence_breakdown: dict
    lookup_status: str
    book_breakdown: dict
    series_breakdown: dict
    search_context: dict
    lvi_match: dict


class MetadataLookupService:
    def __init__(self, conn: sqlite3.Connection):
        email = os.environ.get("METADATA_CONTACT_EMAIL", "local-dev")
        ua = f"SeedboxAudiobookStager/0.1 (contact: {email})"
        self.client = RateLimitedClient(
            audnexus_min_ms=int(os.environ.get("AUDNEXUS_MIN_INTERVAL_MS", "500")),
            openlibrary_min_ms=int(os.environ.get("OPENLIBRARY_MIN_INTERVAL_MS", "1000")),
            mam_requests_per_minute=int(os.environ.get("MAM_REQUESTS_PER_MINUTE", "120")),
            user_agent=ua,
        )
        self.cache = ApiCache(conn)
        cookie_path = stager_mam_cookie_path()
        mam_id = resolve_mam_id()
        if mam_id and cookie_path is not None and not cookie_path.is_file():
            persist_stager_mam_cookie(mam_id, cookie_path)
        from stager_core.metadata.fixture_providers import (
            FixtureMetadataProviders,
            fixture_backend_enabled,
        )

        if fixture_backend_enabled():
            self.providers = FixtureMetadataProviders()
            logger.info("Metadata providers: fixture backend (no network)")
        else:
            self.providers = MetadataProviders(
                self.client,
                self.cache,
                region=os.environ.get("AUDNEXUS_REGION", "us"),
                google_api_key=os.environ.get("GOOGLE_BOOKS_API_KEY", ""),
                mam_id=mam_id,
                mam_cookie_path=cookie_path,
            )
            if mam_id:
                logger.info("MAM metadata search enabled (cookie len %d)", len(mam_id))
            else:
                logger.info("MAM metadata search disabled (no Stager mam_id)")
        self._lock = threading.Lock()
        self._author_catalog_cache: dict[str, list[MetadataCandidate]] = {}
        self._title_first_cache: dict[str, list[MetadataCandidate]] = {}

    def wait_status(self) -> str:
        return self.client.wait_status()

    def provider_status(self) -> list[dict]:
        return list_provider_status()

    def test_providers(self) -> list[dict]:
        return test_all_providers(self.providers)

    def lookup_book(
        self,
        source_root: Path,
        book: FlatBook,
        manual: ManualHints | None = None,
        *,
        lvi_options: LviLookupOptions | None = None,
    ) -> tuple[list[MetadataCandidate], TagInfo]:
        resolution = self.resolve_book(source_root, book, manual, lvi_options=lvi_options)
        return resolution.candidates, resolution.tags

    def resolve_book(
        self,
        source_root: Path,
        book: FlatBook,
        manual: ManualHints | None = None,
        *,
        lvi_options: LviLookupOptions | None = None,
    ) -> LookupResolution:
        with self._lock:
            return self._resolve_book_locked(source_root, book, manual, lvi_options=lvi_options)

    def _local_candidates(
        self, book: FlatBook, tags: TagInfo, context: dict[str, str]
    ) -> list[MetadataCandidate]:
        local: list[MetadataCandidate] = []

        id3 = tag_candidate(tags)
        if id3:
            id3.title = normalize_title(id3.title) or id3.title
            id3.author = normalize_author(id3.author) or id3.author
            local.append(id3)

        folder_title = normalize_title(context.get("folder_title") or "")
        folder_author = normalize_author(context.get("author") or "")
        if folder_title:
            local.append(
                MetadataCandidate(
                    author=folder_author or "Unknown Author",
                    title=folder_title,
                    source="folder",
                    confidence=0.0,
                )
            )

        if book.files:
            stem = stem_base(book.files[0].name.rsplit(".", 1)[0])
            filename_title = normalize_title(stem)
            if filename_title:
                local.append(
                    MetadataCandidate(
                        author=folder_author,
                        title=filename_title,
                        source="filename",
                        confidence=0.0,
                    )
                )
        return local

    def _external_candidates(self, title: str, author: str) -> list[MetadataCandidate]:
        """Query each external provider with combined title+author only.

        Title-only rescue is handled by ``_title_first_candidates`` (parallel pass).
        """
        pooled: list[MetadataCandidate] = []
        seen: set[tuple[str, str, str]] = set()

        def add(cands: list[MetadataCandidate]) -> None:
            for cand in cands:
                if not cand.title.strip():
                    continue
                key = (
                    cand.source,
                    normalize_author(cand.author).lower(),
                    normalize_title(cand.title).lower(),
                )
                if key in seen:
                    continue
                seen.add(key)
                pooled.append(cand)

        searches: tuple[tuple[str, object], ...] = (
            ("audible", self.providers.audible_search),
            ("mam", self.providers.mam_search),
            ("google", self.providers.google_books_search),
            ("openlibrary", self.providers.openlibrary_search),
        )
        for _name, search in searches:
            combined = [c for c in search(title, author) if c.title.strip()]
            if combined:
                add(combined)
        return pooled

    def _title_first_candidates(self, title: str) -> list[MetadataCandidate]:
        return title_first_candidates(
            self.providers,
            title,
            title_cache=self._title_first_cache,
        )

    def _author_oeuvre_candidate(
        self,
        book: FlatBook,
        tags: TagInfo,
        context: dict,
        manual: ManualHints | None,
    ) -> MetadataCandidate | None:
        return author_oeuvre_candidate(
            self.providers,
            book,
            tags,
            context,
            manual,
            self._author_catalog_cache,
        )

    def _resolve_book_locked(
        self,
        source_root: Path,
        book: FlatBook,
        manual: ManualHints | None = None,
        *,
        lvi_options: LviLookupOptions | None = None,
    ) -> LookupResolution:
        opts = lvi_options or LviLookupOptions()
        file_sources = [f.source for f in book.files]
        tags = read_book_tags(source_root, file_sources)
        context = build_search_context(book, tags, manual)

        lvi_match = resolve_lvi_match(opts.lvi, book, tags)
        apply_lvi_search(context, lvi_match, enabled=opts.lvi_search)

        if manual and (manual.title or "").strip():
            title = normalize_title(manual.title) or manual.title.strip()
        else:
            extraction_cfg = opts.title_extraction or TitleExtractionConfig()
            title = extract_title(book, tags, extraction_cfg)
            title = normalize_title(title) or title
        author = normalize_author(context["author"]) or context["author"]

        candidates: list[MetadataCandidate] = []

        if context["asin"]:
            candidates.extend(self.providers.audnexus_book(context["asin"]))
        candidates.extend(self._title_first_candidates(title))
        candidates.extend(self._external_candidates(title, author))
        if author.strip():
            oeuvre = self._author_oeuvre_candidate(book, tags, context, manual)
            if oeuvre:
                candidates.append(oeuvre)
        candidates.extend(self._local_candidates(book, tags, context))

        candidates = [c for c in candidates if c.source != "audnexus_author" and c.title.strip()]

        annotate_candidates_lvi(candidates, opts.lvi)

        evidence = [
            Evidence(
                source=c.source,
                author=c.author,
                title=c.title,
                weight=source_prior(c.source),
                extras={"candidate": c},
            )
            for c in candidates
        ]
        if opts.lvi_boost:
            evidence.extend(library_corroboration_evidence(candidates))

        winner, book_breakdown = pick_winner(evidence)
        annotate_candidates(candidates, book_breakdown)

        suggested_author = ""
        suggested_title = ""
        book_leg = 0.0
        lookup_status = "no_match"
        if winner:
            suggested_author = winner.author
            suggested_title = winner.title
            book_leg = float(winner.confidence or book_breakdown.get("confidence") or 0)
            lookup_status = "ok"
        else:
            suggested_title = book.flatten_name
            lookup_status = book_breakdown.get("status") or "no_match"

        series_votes = pick_series_votes_from_cluster(book_breakdown, candidates)
        id3_vote = id3_series_vote(tags)
        if id3_vote:
            series_votes.append(id3_vote)
        lvi_vote = lvi_series_vote(lvi_match, enabled=opts.lvi_boost)
        if lvi_vote:
            series_votes.append(lvi_vote)

        series, series_index, series_leg, series_state, series_breakdown = pick_series(series_votes)
        annotate_series_membership(candidates, series_breakdown)
        staging_confidence, confidence_breakdown = fold_staging_confidence(
            book_leg, series_leg, series_state
        )
        confidence_breakdown["series_breakdown"] = series_breakdown
        confidence_breakdown["book_breakdown"] = book_breakdown
        if winner:
            winner.score_breakdown = {
                **book_breakdown,
                "confidence_breakdown": confidence_breakdown,
                "series_breakdown": series_breakdown,
            }

        def sort_key(c: MetadataCandidate) -> tuple[int, int, int, float, float]:
            lvi_tier = candidate_sort_lvi_tier(c) if opts.lvi_boost else 0
            if c.in_winning_cluster:
                return (lvi_tier, 0, c.medoid_rank or 999, 0.0, 0.0)
            return (lvi_tier, 1, 0, -c.cluster_confidence, -c.medoid_score)

        candidates.sort(key=sort_key)

        if not (series or "").strip() and not (series_index or "").strip():
            cand_series, cand_index = primary_candidate_series_from_candidates(candidates)
            if cand_series or cand_index:
                series = cand_series
                series_index = cand_index
                series_state = "confirmed" if cand_series else "unknown"

        return LookupResolution(
            candidates=candidates,
            tags=tags,
            suggested_author=suggested_author,
            suggested_title=suggested_title,
            suggested_series=series,
            suggested_series_index=series_index,
            suggested_series_state=series_state,
            suggested_series_source=series_breakdown.get("winning_source", ""),
            confidence=staging_confidence,
            confidence_breakdown=confidence_breakdown,
            lookup_status=lookup_status,
            book_breakdown=book_breakdown,
            series_breakdown=series_breakdown,
            search_context=context,
            lvi_match=lvi_match.to_dict(),
        )


def annotate_candidates(candidates: list[MetadataCandidate], breakdown: dict) -> None:
    """Attach cluster confidence, centrality, and sort metadata for UI display."""
    if not breakdown or breakdown.get("status") == "no_match":
        return
    pool = breakdown.get("evidence_pool") or []
    rep = breakdown.get("representative") or {}
    winner_conf = float(breakdown.get("confidence") or 0.0)

    winning_cluster_id: int | None = None
    for entry in pool:
        if (
            entry.get("source") == rep.get("source")
            and entry.get("author") == rep.get("author")
            and entry.get("title") == rep.get("title")
        ):
            winning_cluster_id = entry.get("cluster_id")
            break

    by_key = {(e["source"], e["author"], e["title"]): e for e in pool}
    for cand in candidates:
        entry = by_key.get((cand.source, cand.author, cand.title))
        if entry is None:
            continue
        cand.cluster_id = int(entry["cluster_id"])
        cand.cluster_confidence = float(entry.get("cluster_confidence") or 0.0)
        cand.cluster_membership = float(entry["membership"])
        cand.medoid_score = float(entry.get("medoid_score") or 0.0)
        cand.in_winning_cluster = (
            winning_cluster_id is not None and cand.cluster_id == winning_cluster_id
        )

    winning = [c for c in candidates if c.in_winning_cluster]
    winning.sort(
        key=lambda c: (-c.medoid_score, -c.cluster_membership, len(c.title or "")),
    )
    for rank, cand in enumerate(winning, start=1):
        cand.medoid_rank = rank

    for cand in candidates:
        if cand.score_breakdown:
            cand.confidence = round(winner_conf, 4)


def pick_suggestion(candidates: list[MetadataCandidate]) -> MetadataCandidate | None:
    for cand in candidates:
        if cand.score_breakdown:
            return cand
    for cand in candidates:
        if cand.title.strip():
            return cand
    return None
