"""Fuzzy subset title matching for metadata lookup."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from stager_core.discovery import (
    FlatBook,
    is_generic_folder_name,
    sanitize_folder_name,
    stem_base,
)
from stager_core.metadata.normalize import is_generic_title, normalize_title
from stager_core.metadata.scoring import _tokens, containment
from stager_core.metadata.tags import CHAPTER_TITLE_RE
from stager_core.metadata.title_cleanup import light_title_cleanup
from stager_core.metadata.types import TagInfo

PrecleanFn = Callable[[str], str]
PostcleanFn = Callable[[str], str]

SUBSET_CONTAINMENT_THRESHOLD = 0.8
_MIN_TOKEN_COUNT = 2

_JUNK_PATH = frozenset({"audiobooks", "books", "audio", "m4b", "mp3", "."})
_NUMERIC_ONLY_RE = re.compile(r"^[\d.\-_ ]+$")


def _best_id3_title(tags: TagInfo) -> str:
    title = (tags.title or "").strip()
    album = (tags.album or "").strip()
    if not title:
        return album
    if not album or title.lower() == album.lower():
        return title
    if CHAPTER_TITLE_RE.match(title):
        return album
    return title


def _filename_stem(book: FlatBook) -> str:
    if not book.files:
        return ""
    return stem_base(book.files[0].name.rsplit(".", 1)[0])


@dataclass(frozen=True)
class _Candidate:
    label: str
    value: str


def _raw_first(tags: TagInfo, key: str) -> str:
    raw = tags.raw or {}
    val = raw.get(key)
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else ""
    return str(val).strip()


def _norm_key(text: str) -> str:
    return normalize_title(text) or (text or "").strip().lower()


def eligible_title(value: str) -> bool:
    """True when a raw or cleaned title is usable for extraction."""
    text = (value or "").strip()
    if not text or text == ".":
        return False
    if _NUMERIC_ONLY_RE.match(text):
        return False
    if CHAPTER_TITLE_RE.match(text):
        return False
    if is_generic_title(text):
        return False
    return True


def _eligible(value: str) -> bool:
    return eligible_title(value)


def _token_count(text: str) -> int:
    return len(_tokens(normalize_title(text) or text))


def _pair_qualifies(a: str, b: str) -> tuple[float, bool]:
    na, nb = normalize_title(a) or a, normalize_title(b) or b
    if not na or not nb:
        return 0.0, False
    score = max(containment(na, nb), containment(nb, na))
    if score < SUBSET_CONTAINMENT_THRESHOLD:
        return score, False
    smaller = min(_token_count(a), _token_count(b))
    if smaller <= _MIN_TOKEN_COUNT:
        if _token_count(a) == 1 and _token_count(b) == 1:
            return score, True
        return score, False
    return score, True


def longest_common_substring(a: str, b: str) -> str:
    """Longest common substring on normalized lowercase text; return original casing."""
    na, nb = normalize_title(a) or a, normalize_title(b) or b
    if not na or not nb:
        return ""
    la, lb = na.lower(), nb.lower()
    if la == lb:
        return na
    best_len, best_end = 0, 0
    prev = [0] * (len(lb) + 1)
    for i in range(1, len(la) + 1):
        curr = [0] * (len(lb) + 1)
        for j in range(1, len(lb) + 1):
            if la[i - 1] == lb[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best_len:
                    best_len = curr[j]
                    best_end = i
            else:
                curr[j] = 0
        prev = curr
    if best_len < 3:
        return ""
    lcs_lower = la[best_end - best_len : best_end]
    for src in (a, b):
        src_norm = normalize_title(src) or src
        idx = src_norm.lower().find(lcs_lower)
        if idx >= 0:
            return src_norm[idx : idx + best_len].strip()
    return lcs_lower.strip()


def _preclean_light(value: str) -> str:
    return light_title_cleanup(value)


def _title_candidates(
    book: FlatBook,
    tags: TagInfo,
    *,
    preclean: PrecleanFn = _preclean_light,
) -> list[_Candidate]:
    out: list[_Candidate] = []
    seen: set[str] = set()

    def add(label: str, value: str) -> None:
        text = preclean(value)
        if not _eligible(text):
            return
        key = _norm_key(text)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(_Candidate(label, text))

    add("id3_album", tags.album or "")
    add("id3_title", tags.title or "")
    best = _best_id3_title(tags)
    if best:
        add("id3_best", best)
    for key in ("grouping", "contentgroup"):
        add(f"id3_raw_{key}", _raw_first(tags, key))
    add("filename_stem", _filename_stem(book))
    for i, part in enumerate(book.source_path_parts):
        if part and part.lower() not in _JUNK_PATH and not is_generic_folder_name(part):
            add(f"path[{i}]", sanitize_folder_name(part))

    return out


def path_deepest_segment(book: FlatBook) -> str:
    """Deepest non-junk path segment (raw, not cleaned)."""
    for part in reversed(book.source_path_parts):
        if not part or part.lower() in _JUNK_PATH or is_generic_folder_name(part):
            continue
        return sanitize_folder_name(part)
    return ""


def path_best_title(book: FlatBook, *, preclean: PrecleanFn = _preclean_light) -> str:
    """Cascade: stem_base → flatten_name → deepest non-junk path segment (pre-cleaned)."""
    if book.files:
        stem = preclean(stem_base(book.files[0].name.rsplit(".", 1)[0]))
        if stem and _eligible(stem):
            return stem.strip()

    flatten = preclean(book.flatten_name or "")
    if flatten and _eligible(flatten):
        return flatten.strip()

    for part in reversed(book.source_path_parts):
        if not part or part.lower() in _JUNK_PATH or is_generic_folder_name(part):
            continue
        candidate = preclean(sanitize_folder_name(part))
        if candidate and _eligible(candidate):
            return candidate.strip()
    return ""


def fuzzy_subset_title(
    book: FlatBook,
    tags: TagInfo,
    *,
    preclean: PrecleanFn = _preclean_light,
    postclean: PostcleanFn | None = None,
) -> str:
    """Pre-clean candidates → LCS subset match → fallback id3_best/path_best (pre-cleaned)."""
    cands = _title_candidates(book, tags, preclean=preclean)
    if not cands:
        raw = path_best_title(book, preclean=preclean) or preclean(_best_id3_title(tags))
        return postclean(raw) if postclean and raw else raw

    best_score = 0.0
    best_lcs = ""
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            score, ok = _pair_qualifies(cands[i].value, cands[j].value)
            if not ok or score <= best_score:
                continue
            lcs = longest_common_substring(cands[i].value, cands[j].value)
            if not lcs or is_generic_title(lcs):
                continue
            best_score = score
            best_lcs = lcs

    if best_lcs:
        return postclean(best_lcs) if postclean else best_lcs

    fallback = preclean(_best_id3_title(tags))
    if fallback and _eligible(fallback):
        return postclean(fallback) if postclean else fallback
    raw = path_best_title(book, preclean=preclean)
    return postclean(raw) if postclean and raw else raw
