"""Library Vocabulary Index (LVI) — staged-library author/series vocabulary.

Built from staged rows in stager.db (not a filesystem walk). Author/series keys
use the same rules as on-disk folder names (``sanitize_folder_name``) so LVI
exact match means "would stage to the same path segment", not fuzzy text fold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from stager_core.discovery import sanitize_folder_name
from stager_core.metadata.scoring import author_sim
from stager_core.metadata.series_scoring import series_sim

DEFAULT_AUTHOR_FLOOR = 0.85
DEFAULT_SERIES_FLOOR = 0.88

_TITLE_INDEX_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*-\s*(.+)$")


def author_key(name: str) -> str:
    """Filesystem-equivalent author folder key (see ``sanitize_folder_name``)."""
    return sanitize_folder_name((name or "").strip())


def series_key(name: str) -> str:
    """Filesystem-equivalent series folder key (see ``sanitize_folder_name``)."""
    return sanitize_folder_name((name or "").strip())


def _parse_title_folder(title_part: str) -> tuple[str, str]:
    m = _TITLE_INDEX_RE.match((title_part or "").strip())
    if m:
        return m.group(1), m.group(2).strip()
    return "", (title_part or "").strip()


def parse_staged_path(staged_path: str) -> dict[str, str]:
    parts = [p for p in (staged_path or "").replace("\\", "/").split("/") if p]
    if len(parts) == 2:
        author, title_part = parts[0], parts[1]
        idx, title = _parse_title_folder(title_part)
        return {"author": author, "title": title, "series": "", "series_index": idx}
    if len(parts) >= 3:
        author, series, title_part = parts[0], parts[1], parts[2]
        idx, title = _parse_title_folder(title_part)
        return {"author": author, "title": title, "series": series, "series_index": idx}
    if len(parts) == 1:
        return {"author": "", "title": parts[0], "series": "", "series_index": ""}
    return {"author": "", "title": "", "series": "", "series_index": ""}


def _flag(row: Any, key: str) -> bool:
    try:
        return bool(int(row[key] or 0))
    except (KeyError, TypeError, ValueError):
        return False


def is_manual_pinned(row: dict[str, Any]) -> bool:
    return any(
        _flag(row, k)
        for k in (
            "chosen_author_set",
            "chosen_title_set",
            "chosen_series_set",
            "chosen_series_index_set",
        )
    )


def _trust_from_row(row: dict[str, Any]) -> float:
    if is_manual_pinned(row):
        return 1.0
    gt = row.get("ground_truth") or {}
    src = str(gt.get("source") or "")
    if "pinned" in src:
        return 1.0
    conf = row.get("confidence")
    if isinstance(conf, (int, float)) and conf >= 0.9:
        return 0.7
    return 0.9


@dataclass
class MatchResult:
    canonical: str
    alias_matched: str
    similarity: float
    trust: float
    score: float
    author_key: str = ""


@dataclass
class AuthorEntry:
    canonical_name: str
    author_key: str
    aliases: set[str] = field(default_factory=set)
    book_count: int = 0
    trust: float = 0.9
    asins: set[str] = field(default_factory=set)


@dataclass
class SeriesEntry:
    canonical_name: str
    series_key: str
    author_key: str
    aliases: set[str] = field(default_factory=set)
    book_count: int = 0
    trust: float = 0.9
    indices_known: set[str] = field(default_factory=set)


@dataclass
class BookEntry:
    author_key: str
    series_key: str
    title: str
    target_key: str
    book_id: str
    asin: str = ""
    trust: float = 0.9


@dataclass
class LibraryVocabulary:
    authors: dict[str, AuthorEntry] = field(default_factory=dict)
    series_by_author: dict[str, dict[str, SeriesEntry]] = field(default_factory=dict)
    books: list[BookEntry] = field(default_factory=list)
    train_book_ids: set[str] = field(default_factory=set)

    @classmethod
    def build_from_rows(
        cls,
        rows: list[dict[str, Any]],
        *,
        exclude_book_ids: set[str] | None = None,
        provider_rows: list[dict[str, Any]] | None = None,
    ) -> LibraryVocabulary:
        del provider_rows
        exclude = exclude_book_ids or set()
        lvi = cls()
        for row in rows:
            book_id = str(row.get("book_id") or "")
            if not book_id or book_id in exclude:
                continue
            if not _is_staged_library_row(row):
                continue
            gt = row.get("ground_truth") or {}
            author = (gt.get("author") or "").strip()
            title = (gt.get("title") or "").strip()
            series = (gt.get("series") or "").strip()
            series_index = (gt.get("series_index") or "").strip()
            if not author:
                continue

            trust = _trust_from_row(row)
            akey = author_key(author)
            lvi.train_book_ids.add(book_id)

            auth = lvi.authors.get(akey)
            if auth is None:
                auth = AuthorEntry(canonical_name=author, author_key=akey, trust=trust)
                lvi.authors[akey] = auth
            auth.book_count += 1
            auth.trust = max(auth.trust, trust)
            for alias in _staged_library_author_aliases(row):
                auth.aliases.add(alias)

            asin = str((row.get("library_tags") or {}).get("asin") or "").strip()
            if asin:
                auth.asins.add(asin)

            skey = series_key(series) if series else ""
            if series:
                by_auth = lvi.series_by_author.setdefault(akey, {})
                sent = by_auth.get(skey)
                if sent is None:
                    sent = SeriesEntry(
                        canonical_name=series,
                        series_key=skey,
                        author_key=akey,
                        trust=trust,
                    )
                    by_auth[skey] = sent
                sent.book_count += 1
                sent.trust = max(sent.trust, trust)
                for alias in _staged_library_series_aliases(row):
                    if alias.strip():
                        sent.aliases.add(alias.strip())
                if series_index:
                    sent.indices_known.add(series_index)

            staged_path = (gt.get("staged_path") or row.get("staged_path") or "").strip()
            target_key = staged_path.replace("\\", "/") if staged_path else f"{author}/{title}"
            lvi.books.append(
                BookEntry(
                    author_key=akey,
                    series_key=skey,
                    title=title,
                    target_key=target_key,
                    book_id=book_id,
                    asin=asin,
                    trust=trust,
                )
            )
        return lvi

    def match_author(self, hint: str, *, floor: float = DEFAULT_AUTHOR_FLOOR) -> MatchResult | None:
        hint = (hint or "").strip()
        if not hint or not self.authors:
            return None
        best: MatchResult | None = None
        for entry in self.authors.values():
            for alias in entry.aliases:
                if not alias.strip():
                    continue
                sim = author_sim(hint, alias)
                if sim < floor:
                    continue
                score = entry.trust * sim
                if best is None or score > best.score:
                    best = MatchResult(
                        canonical=entry.canonical_name,
                        alias_matched=alias,
                        similarity=sim,
                        trust=entry.trust,
                        score=score,
                        author_key=entry.author_key,
                    )
        return best

    def match_series(
        self,
        hint: str,
        author_key_val: str,
        *,
        floor: float = DEFAULT_SERIES_FLOOR,
    ) -> MatchResult | None:
        hint = (hint or "").strip()
        if not hint or not author_key_val:
            return None
        by_auth = self.series_by_author.get(author_key_val) or {}
        if not by_auth:
            return None
        best: MatchResult | None = None
        for entry in by_auth.values():
            for alias in entry.aliases:
                if not alias.strip():
                    continue
                raw = series_sim(hint, alias)
                sim = float(raw) if isinstance(raw, (int, float)) else (1.0 if raw else 0.0)
                if sim < floor:
                    continue
                score = entry.trust * sim
                if best is None or score > best.score:
                    best = MatchResult(
                        canonical=entry.canonical_name,
                        alias_matched=alias,
                        similarity=sim,
                        trust=entry.trust,
                        score=score,
                        author_key=entry.author_key,
                    )
        return best

    def match_author_exact(self, name: str) -> MatchResult | None:
        """Exact author match on filesystem-equivalent keys (candidate boost / UI)."""
        key = author_key(name)
        if not key or not self.authors:
            return None
        for entry in self.authors.values():
            if entry.author_key == key:
                return MatchResult(
                    canonical=entry.canonical_name,
                    alias_matched=entry.canonical_name,
                    similarity=1.0,
                    trust=entry.trust,
                    score=entry.trust,
                    author_key=entry.author_key,
                )
            for alias in entry.aliases:
                if alias.strip() and author_key(alias) == key:
                    return MatchResult(
                        canonical=entry.canonical_name,
                        alias_matched=alias,
                        similarity=1.0,
                        trust=entry.trust,
                        score=entry.trust,
                        author_key=entry.author_key,
                    )
        return None

    def match_series_exact(self, name: str, author_key_val: str) -> MatchResult | None:
        """Exact series match on filesystem-equivalent keys (candidate boost / UI)."""
        key = series_key(name)
        if not key or not author_key_val:
            return None
        by_auth = self.series_by_author.get(author_key_val) or {}
        for entry in by_auth.values():
            if entry.series_key == key:
                return MatchResult(
                    canonical=entry.canonical_name,
                    alias_matched=entry.canonical_name,
                    similarity=1.0,
                    trust=entry.trust,
                    score=entry.trust,
                    author_key=entry.author_key,
                )
            for alias in entry.aliases:
                if alias.strip() and series_key(alias) == key:
                    return MatchResult(
                        canonical=entry.canonical_name,
                        alias_matched=alias,
                        similarity=1.0,
                        trust=entry.trust,
                        score=entry.trust,
                        author_key=entry.author_key,
                    )
        return None

    def summary(self) -> dict[str, Any]:
        n_series = sum(len(v) for v in self.series_by_author.values())
        n_aliases = sum(len(e.aliases) for e in self.authors.values())
        return {
            "n_authors": len(self.authors),
            "n_series": n_series,
            "n_books": len(self.books),
            "n_aliases": n_aliases,
            "train_book_ids": len(self.train_book_ids),
        }


def _is_staged_library_row(row: dict[str, Any]) -> bool:
    if row.get("staged") is False:
        return False
    if str(row.get("db_status") or "") == "pending":
        return False
    gt = row.get("ground_truth") or {}
    staged_path = (gt.get("staged_path") or row.get("staged_path") or "").strip()
    if not staged_path or staged_path in {".", "/"}:
        return False
    parts = [p for p in staged_path.replace("\\", "/").split("/") if p]
    return len(parts) >= 2


def _staged_path_parts(row: dict[str, Any]) -> list[str]:
    gt = row.get("ground_truth") or {}
    staged_path = (gt.get("staged_path") or row.get("staged_path") or "").strip()
    return [p for p in staged_path.replace("\\", "/").split("/") if p]


def _staged_library_author_aliases(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    gt = row.get("ground_truth") or {}
    author = (gt.get("author") or "").strip()
    if author:
        out.add(author)
    chosen = (row.get("chosen_author") or "").strip()
    if chosen:
        out.add(chosen)
    parts = _staged_path_parts(row)
    if parts:
        out.add(parts[0])
        parsed = parse_staged_path("/".join(parts))
        if parsed.get("author"):
            out.add(parsed["author"])
    lib_tags = row.get("library_tags") or {}
    for key in ("artist", "albumartist"):
        val = (lib_tags.get(key) or "").strip()
        if val:
            out.add(val)
    return out


def _staged_library_series_aliases(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    gt = row.get("ground_truth") or {}
    series = (gt.get("series") or "").strip()
    if series:
        out.add(series)
    chosen = (row.get("chosen_series") or "").strip()
    if chosen:
        out.add(chosen)
    parts = _staged_path_parts(row)
    if len(parts) >= 3:
        out.add(parts[1])
        parsed = parse_staged_path("/".join(parts))
        if parsed.get("series"):
            out.add(parsed["series"])
    return out
