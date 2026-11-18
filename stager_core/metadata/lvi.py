"""LVI build, hint resolution, and lookup integration helpers."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from stager_core.discovery import FlatBook, stem_base
from stager_core.metadata.library_vocab import (
    DEFAULT_AUTHOR_FLOOR,
    DEFAULT_SERIES_FLOOR,
    LibraryVocabulary,
    author_key,
    is_manual_pinned,
    parse_staged_path,
)
from stager_core.metadata.normalize import provider_text
from stager_core.metadata.scoring import Evidence, source_prior
from stager_core.metadata.series_scoring import SeriesVote
from stager_core.metadata.tags import TagInfo
from stager_core.metadata.types import MetadataCandidate

_JUNK_PATH = frozenset({"audiobooks", "books", "audio", "m4b", "mp3"})
_ID3_AUTHOR_KEYS = ("id3.artist", "id3.albumartist")
_PATH_AUTHOR_PREFIX = "path.author_candidate"
_SERIES_HINT_KEYS = (
    "id3_series.series",
    "id3.raw.grouping",
    "id3.raw.contentgroup",
    "folder.grandparent_dir",
    "folder.parent_dir",
)


def _flag(row: sqlite3.Row, key: str) -> bool:
    try:
        return bool(int(row[key] or 0))
    except (KeyError, TypeError, ValueError):
        return False


def ground_truth_from_row(row: sqlite3.Row) -> dict[str, str] | None:
    status = str(row["status"] or "")
    if status != "staged":
        return None
    staged_path = str(row["staged_path"] or "").strip()
    if not staged_path:
        return None

    parsed = parse_staged_path(staged_path)
    sources: list[str] = []

    if _flag(row, "chosen_author_set") and str(row["chosen_author"] or "").strip():
        author = str(row["chosen_author"]).strip()
        sources.append("author:pinned")
    elif str(row["chosen_author"] or "").strip():
        author = str(row["chosen_author"]).strip()
        sources.append("author:chosen_unpinned")
    else:
        author = parsed["author"]
        sources.append("author:parsed")

    if _flag(row, "chosen_title_set") and str(row["chosen_title"] or "").strip():
        title = str(row["chosen_title"]).strip()
        sources.append("title:pinned")
    elif str(row["chosen_title"] or "").strip():
        title = str(row["chosen_title"]).strip()
        sources.append("title:chosen_unpinned")
    else:
        title = parsed["title"]
        sources.append("title:parsed")

    if _flag(row, "chosen_series_set"):
        series = str(row["chosen_series"] or "").strip()
        sources.append("series:pinned")
    elif str(row["chosen_series"] or "").strip():
        series = str(row["chosen_series"]).strip()
        sources.append("series:chosen_unpinned")
    else:
        series = parsed["series"]
        sources.append("series:parsed")

    if _flag(row, "chosen_series_index_set") and str(row["chosen_series_index"] or "").strip():
        series_index = str(row["chosen_series_index"]).strip()
        sources.append("index:pinned")
    elif str(row["chosen_series_index"] or "").strip():
        series_index = str(row["chosen_series_index"]).strip()
        sources.append("index:chosen_unpinned")
    else:
        series_index = parsed["series_index"]
        sources.append("index:parsed")

    source_label = "mixed" if len(set(sources)) > 1 else (sources[0] if sources else "parsed")
    return {
        "author": author,
        "title": title,
        "series": series,
        "series_index": series_index,
        "staged_path": staged_path,
        "source": source_label,
    }


def build_lvi_rows_from_db(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in conn.execute("SELECT * FROM books WHERE status = 'staged' ORDER BY source_path"):
        gt = ground_truth_from_row(row)
        if gt is None:
            continue
        tags: dict[str, Any] = {}
        try:
            tags = json.loads(row["tags_json"] or "{}")
        except json.JSONDecodeError:
            pass
        rows.append({
            "book_id": row["id"],
            "source_path": row["source_path"],
            "db_status": row["status"],
            "staged": True,
            "staged_path": gt["staged_path"],
            "ground_truth": gt,
            "confidence": float(row["confidence"] or 0),
            "chosen_author": row["chosen_author"] or "",
            "chosen_series": row["chosen_series"] or "",
            "chosen_author_set": int(row["chosen_author_set"] or 0),
            "chosen_title_set": int(row["chosen_title_set"] or 0),
            "chosen_series_set": int(row["chosen_series_set"] or 0),
            "chosen_series_index_set": int(row["chosen_series_index_set"] or 0),
            "library_tags": tags,
        })
    return rows


def build_lvi_from_db(
    conn: sqlite3.Connection,
    *,
    exclude_book_ids: set[str] | None = None,
) -> LibraryVocabulary:
    return LibraryVocabulary.build_from_rows(
        build_lvi_rows_from_db(conn),
        exclude_book_ids=exclude_book_ids,
    )


def lvi_for_book(
    base: LibraryVocabulary | None,
    rows: list[dict[str, Any]] | None,
    book_id: str,
) -> LibraryVocabulary | None:
    """Return LVI excluding the book being resolved (avoid self-match)."""
    if base is None or not rows:
        return None
    return LibraryVocabulary.build_from_rows(rows, exclude_book_ids={book_id})


def local_signals(book: FlatBook, tags: TagInfo) -> dict[str, str]:
    raw = tags.raw or {}
    parts = list(book.source_path_parts) or [
        p for p in book.source_path.replace("\\", "/").split("/") if p
    ]
    parent = parts[-2] if len(parts) >= 2 else ""
    grandparent = parts[-3] if len(parts) >= 3 else ""
    first_stem = book.files[0].name.rsplit(".", 1)[0] if book.files else ""

    def raw_first(key: str) -> str:
        val = raw.get(key)
        if val is None:
            return ""
        if isinstance(val, (list, tuple)):
            return str(val[0]).strip() if val else ""
        return str(val).strip()

    series_raw = raw_first("contentgroup") or raw_first("grouping") or ""
    signals: dict[str, str] = {
        "folder.parent_dir": parent,
        "folder.grandparent_dir": grandparent,
        "folder.parent_context": book.parent_context or "",
        "folder.top_level_pack": book.top_level_pack or "",
        "id3.artist": (tags.artist or "").strip(),
        "id3.albumartist": (tags.albumartist or "").strip(),
        "id3.raw.grouping": raw_first("grouping"),
        "id3.raw.contentgroup": raw_first("contentgroup"),
        "id3_series.series": series_raw,
    }
    skip = _JUNK_PATH
    for i, part in enumerate(reversed(parts)):
        if part and part.lower() not in skip:
            signals[f"path.author_candidate[-{i + 1}]"] = part
    if first_stem:
        signals["file.first_stem_base"] = stem_base(first_stem)
    return signals


def _hint_usable(val: str) -> bool:
    val = (val or "").strip()
    if not val:
        return False
    if val.lower() in _JUNK_PATH:
        return False
    return True


def author_hints(signals: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in _ID3_AUTHOR_KEYS:
        val = (signals.get(key) or "").strip()
        if _hint_usable(val) and val.lower() not in seen:
            out.append(val)
            seen.add(val.lower())
    for key in sorted(k for k in signals if k.startswith(_PATH_AUTHOR_PREFIX)):
        val = (signals.get(key) or "").strip()
        if _hint_usable(val) and val.lower() not in seen:
            out.append(val)
            seen.add(val.lower())
    for key in ("folder.top_level_pack", "folder.parent_dir", "folder.grandparent_dir"):
        val = (signals.get(key) or "").strip()
        if _hint_usable(val) and val.lower() not in seen:
            out.append(val)
            seen.add(val.lower())
    return out


def series_hints(signals: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in _SERIES_HINT_KEYS:
        val = (signals.get(key) or "").strip()
        if val and val.lower() not in seen:
            out.append(val)
            seen.add(val.lower())
    return out


@dataclass
class LviFormMatch:
    """Exact LVI match for author/series strings (edit fields or candidates)."""

    author: str = ""
    series: str = ""
    author_matched: bool = False
    series_matched: bool = False
    book_count_author: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "series": self.series,
            "author_matched": self.author_matched,
            "series_matched": self.series_matched,
            "book_count_author": self.book_count_author,
        }


def resolve_lvi_form_match(
    lvi: LibraryVocabulary | None,
    author: str,
    series: str = "",
) -> LviFormMatch:
    """Exact filesystem-key match for manual edit values (same rules as candidate chrome)."""
    if lvi is None or not lvi.authors:
        return LviFormMatch()
    author_m = lvi.match_author_exact(provider_text(author))
    if author_m is None:
        return LviFormMatch()
    ent = lvi.authors.get(author_m.author_key)
    book_count = ent.book_count if ent else 0
    result = LviFormMatch(
        author=author_m.canonical,
        author_matched=True,
        book_count_author=book_count,
    )
    series_text = provider_text(series)
    if series_text:
        sm = lvi.match_series_exact(series_text, author_m.author_key)
        if sm:
            result.series = sm.canonical
            result.series_matched = True
    return result


@dataclass
class LviMatch:
    author: str = ""
    series: str = ""
    author_hit: bool = False
    series_hit: bool = False
    alias_matched: str = ""
    book_count_author: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "series": self.series,
            "author_hit": self.author_hit,
            "series_hit": self.series_hit,
            "alias_matched": self.alias_matched,
            "book_count_author": self.book_count_author,
        }


def resolve_lvi_match(
    lvi: LibraryVocabulary | None,
    book: FlatBook,
    tags: TagInfo,
    *,
    author_floor: float = DEFAULT_AUTHOR_FLOOR,
    series_floor: float = DEFAULT_SERIES_FLOOR,
) -> LviMatch:
    if lvi is None or not lvi.authors:
        return LviMatch()
    signals = local_signals(book, tags)
    author = ""
    author_hit = False
    alias_matched = ""
    for hint in author_hints(signals):
        m = lvi.match_author(hint, floor=author_floor)
        if m:
            author = m.canonical
            author_hit = True
            alias_matched = m.alias_matched
            break

    series = ""
    series_hit = False
    if author_hit:
        akey = author_key(author)
        best_name = ""
        best_score = -1.0
        for hint in series_hints(signals):
            m = lvi.match_series(hint, akey, floor=series_floor)
            if m and m.score > best_score:
                best_score = m.score
                best_name = m.canonical
                series_hit = True
        series = best_name

    book_count = 0
    if author_hit:
        ent = lvi.authors.get(author_key(author))
        if ent:
            book_count = ent.book_count

    return LviMatch(
        author=author,
        series=series,
        author_hit=author_hit,
        series_hit=series_hit,
        alias_matched=alias_matched,
        book_count_author=book_count,
    )


def apply_lvi_search(
    context: dict[str, str],
    lvi_match: LviMatch,
    *,
    enabled: bool,
) -> dict[str, str]:
    raw_author = context.get("author") or ""
    context["raw_author"] = raw_author
    context["lvi_author"] = lvi_match.author
    context["lvi_series"] = lvi_match.series
    context["lvi_author_hit"] = "1" if lvi_match.author_hit else "0"
    context["lvi_series_hit"] = "1" if lvi_match.series_hit else "0"
    context["lvi_alias_matched"] = lvi_match.alias_matched
    if enabled and lvi_match.author_hit and lvi_match.author.strip():
        context["author"] = lvi_match.author
    if enabled and lvi_match.series_hit and lvi_match.series.strip():
        context["lvi_resolved_series"] = lvi_match.series
    return context


def annotate_candidates_lvi(
    candidates: list[MetadataCandidate],
    lvi: LibraryVocabulary | None,
) -> None:
    """Tag candidates for library boost/UI using exact author/series key matches only."""
    if lvi is None:
        return
    for cand in candidates:
        author_m = lvi.match_author_exact(provider_text(cand.author))
        author_score = author_m.score if author_m else 0.0
        series_score = 0.0
        series_matched = False
        series_text = provider_text(cand.series)
        if author_m and series_text:
            sm = lvi.match_series_exact(series_text, author_m.author_key)
            if sm:
                series_score = sm.score
                series_matched = True
        cand.lvi_author_match = round(author_score, 4)
        cand.lvi_series_match = round(series_score, 4)
        cand.lvi_author_matched = author_m is not None
        cand.lvi_series_matched = series_matched
        cand.lvi_in_library = author_m is not None


_LVI_CANDIDATE_KEYS = (
    "lvi_author_match",
    "lvi_series_match",
    "lvi_author_matched",
    "lvi_series_matched",
    "lvi_in_library",
)


def candidate_from_dict(raw: dict[str, Any]) -> MetadataCandidate:
    return MetadataCandidate(
        author=str(raw.get("author") or ""),
        title=str(raw.get("title") or ""),
        source=str(raw.get("source") or ""),
        confidence=float(raw.get("confidence") or 0),
        narrator=str(raw.get("narrator") or ""),
        series=str(raw.get("series") or ""),
        series_index=str(raw.get("series_index") or ""),
        subtitle=str(raw.get("subtitle") or ""),
        asin=str(raw.get("asin") or ""),
        isbn=str(raw.get("isbn") or ""),
        language=str(raw.get("language") or ""),
        publisher=str(raw.get("publisher") or ""),
        year=str(raw.get("year") or ""),
        description=str(raw.get("description") or ""),
        cover_url=str(raw.get("cover_url") or ""),
        cluster_id=int(raw.get("cluster_id") or -1),
        cluster_confidence=float(raw.get("cluster_confidence") or 0),
        cluster_membership=float(raw.get("cluster_membership") or 0),
        in_winning_cluster=bool(raw.get("in_winning_cluster")),
        medoid_score=float(raw.get("medoid_score") or 0),
        medoid_rank=int(raw.get("medoid_rank") or 0),
        series_membership=float(raw.get("series_membership") or 0),
    )


def refresh_candidates_lvi(
    candidates: list[dict[str, Any]],
    lvi: LibraryVocabulary | None,
) -> list[dict[str, Any]]:
    """Recompute LVI chrome on stored candidate dicts (do not trust persisted flags)."""
    if not candidates:
        return candidates
    objs = [candidate_from_dict(c) for c in candidates]
    annotate_candidates_lvi(objs, lvi)
    out: list[dict[str, Any]] = []
    for raw, obj in zip(candidates, objs):
        row = dict(raw)
        for key in _LVI_CANDIDATE_KEYS:
            row[key] = getattr(obj, key)
        out.append(row)
    return out


def library_corroboration_evidence(
    candidates: list[MetadataCandidate],
) -> list[Evidence]:
    out: list[Evidence] = []
    seen: set[tuple[str, str, str]] = set()
    for cand in candidates:
        if not cand.lvi_author_matched:
            continue
        key = (cand.source, cand.author, cand.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Evidence(
                source="library",
                author=cand.author,
                title=cand.title,
                weight=source_prior("library"),
                extras={"candidate": cand, "lvi_corroboration": True},
            )
        )
    return out


def lvi_series_vote(
    lvi_match: LviMatch,
    *,
    enabled: bool,
) -> SeriesVote | None:
    if not enabled or not lvi_match.series_hit or not lvi_match.series.strip():
        return None
    return SeriesVote(family="library", series=lvi_match.series, series_index="")


def candidate_sort_lvi_tier(c: MetadataCandidate) -> int:
    return 0 if c.lvi_in_library else 1
