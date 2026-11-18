"""Targeted title cleanup for metadata extraction (author/series bundling in ID3/path)."""

from __future__ import annotations

import re

from stager_core.discovery import FlatBook, is_generic_folder_name, sanitize_folder_name
from stager_core.metadata.normalize import normalize_title, split_subtitle, strip_title_edges
from stager_core.metadata.tags import SERIES_ALBUM_RE
from stager_core.metadata.types import TagInfo

_JUNK_PATH = frozenset({"audiobooks", "books", "audio", "m4b", "mp3"})

_JUNK_SUBTITLE_TAILS = frozenset({
    "a novel",
    "the novel",
    "a novel unabridged",
    "unabridged",
    "abridged",
    "audiobook",
    "audio book",
    "dramatized",
})

_LEADING_INDEX_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:rote|rotf)\s*\d+\s+|"
    r"\d{1,3}\s*[\-._]\s*|"
    r"[a-z]{2,10}\s*\d{1,3}\s+"
    r")",
    re.IGNORECASE,
)
_SERIES_BOOK_SUFFIX_RE = re.compile(
    r"\s*[,;]?\s*(?:"
    r"(?:the\s+)?[a-z][\w\s'&-]{0,40}?\s+)?"
    r"(?:series\s*,?\s*)?"
    r"(?:book|bk\.?|vol(?:ume)?\.?)\s*#?\d+"
    r".*$",
    re.IGNORECASE,
)
_MULTIPART_SUFFIX_RE = re.compile(r"\s*\(\s*\d+\s+of\s+\d+\s*\)\s*$", re.IGNORECASE)
_LEADING_TRACK_RE = re.compile(r"^\d{1,3}\s*[-–—]\s*(.+)$")
_INLINE_INDEX_RE = re.compile(r"^.+\s+\d{1,2}\s*[-–—]\s*(.+)$")
_PART_SUFFIX_RE = re.compile(
    r"(?:\s*[-–—]\s*|\s+)(?:part|pt\.?)\s*#?\s*\d{1,3}\s*$",
    re.IGNORECASE,
)
_NARRATOR_PAREN_RE = re.compile(r"\s*\([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\)\s*$")
_DASH_SEP_RE = re.compile(r"\s+[-–—]\s+")
_BY_AUTHOR_RE = re.compile(r"\s+by\s+", re.IGNORECASE)
_COLLECTION_PREFIX_RE = re.compile(
    r"^[A-Z][\w\s.'-]{2,40}\s+collection\s*[-:]\s*",
    re.IGNORECASE,
)


def _collapse(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _author_variants(author: str) -> list[str]:
    raw = _collapse(author)
    if not raw:
        return []
    out = [raw]
    if "," in raw:
        last, _, first = raw.partition(",")
        combined = _collapse(f"{first} {last}")
        if combined:
            out.append(combined)
    parts = raw.split()
    if len(parts) >= 2:
        out.append(parts[-1])
    seen: set[str] = set()
    uniq: list[str] = []
    for v in out:
        key = _fold(v)
        if key and key not in seen:
            seen.add(key)
            uniq.append(v)
    return uniq


def author_hints(book: FlatBook, tags: TagInfo) -> list[str]:
    hints: list[str] = []
    for val in (tags.artist, tags.albumartist):
        s = (val or "").strip()
        if s:
            hints.append(s)
    parts = book.source_path_parts
    ancestor_parts = parts[:-1] if len(parts) > 1 else []
    album_fold = _fold(tags.album or "")
    flatten_fold = _fold(book.flatten_name or "")
    for part in reversed(ancestor_parts):
        if part and part.lower() not in _JUNK_PATH and not is_generic_folder_name(part):
            candidate = sanitize_folder_name(part)
            cf = _fold(candidate)
            if cf and (album_fold.startswith(cf) or flatten_fold.startswith(cf)):
                continue
            hints.append(candidate)
    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        key = _fold(h)
        if key and key not in seen:
            seen.add(key)
            out.append(h)
    return out


def series_hints(book: FlatBook, tags: TagInfo) -> list[str]:
    raw = tags.raw or {}

    def raw_first(key: str) -> str:
        val = raw.get(key)
        if val is None:
            return ""
        if isinstance(val, (list, tuple)):
            return str(val[0]).strip() if val else ""
        return str(val).strip()

    hints: list[str] = []
    for val in (raw_first("contentgroup"), raw_first("grouping")):
        if val:
            hints.append(val)

    parts = book.source_path_parts
    if len(parts) >= 3:
        candidate = sanitize_folder_name(parts[-2])
        if candidate and not is_generic_folder_name(candidate):
            hints.append(candidate)
    if book.parent_context:
        hints.append(sanitize_folder_name(book.parent_context))

    for src in (tags.album, book.flatten_name):
        s = (src or "").strip()
        m = re.search(
            r"(?<![-–—]\s)([A-Za-z][\w\s'-]{0,28}[A-Za-z])\s*,\s*book\s*#?\d+",
            s,
            re.IGNORECASE,
        )
        if m:
            hints.append(m.group(1).strip())

    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        key = _fold(h)
        if key and key not in seen:
            seen.add(key)
            out.append(h)
    return out


def strip_author_prefix(title: str, authors: list[str]) -> str:
    text = (title or "").strip()
    if not text or not authors:
        return text
    for author in authors:
        for variant in _author_variants(author):
            if len(variant) < 4 and " " not in variant:
                continue
            for sep in (" - ", " – ", " — ", ": "):
                prefix = f"{variant}{sep}"
                if text.lower().startswith(prefix.lower()):
                    return text[len(prefix) :].strip()
    return text


def strip_by_author_suffix(title: str, authors: list[str]) -> str:
    text = (title or "").strip()
    if not text or not authors:
        return text
    m = _BY_AUTHOR_RE.search(text)
    if not m:
        return text
    head, tail = text[: m.start()].strip(), text[m.end() :].strip()
    if not head or not tail:
        return text
    tail_fold = _fold(tail)
    for author in authors:
        for variant in _author_variants(author):
            if _fold(variant) == tail_fold or _fold(variant).endswith(tail_fold):
                return head
    return text


def strip_series_book_suffix(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return text
    m = re.search(
        r"^(?P<head>.+?)\s*,\s*(?:(?:book|bk\.?|vol(?:ume)?\.?)\s*#?\d+.*)$",
        text,
        re.IGNORECASE,
    )
    if m:
        head = m.group("head").strip()
        if head and len(head.split()) >= 2:
            return head
    m = re.search(
        r"^(?P<head>.+?)\s+(?:(?:book|bk\.?|vol(?:ume)?\.?)\s*#?\d+)\s*$",
        text,
        re.IGNORECASE,
    )
    if m:
        head = m.group("head").strip()
        if head and len(head.split()) >= 3:
            return head
    return text


def strip_series_name(title: str, series_names: list[str]) -> str:
    text = (title or "").strip()
    if not text or not series_names:
        return text
    out = text
    text_fold = _fold(text)
    for series in series_names:
        s = (series or "").strip()
        sf = _fold(s)
        if not s or len(sf) < 3:
            continue
        if text_fold.startswith(sf) or sf == text_fold.split(":")[0].strip():
            continue
        if sf == text_fold:
            continue
        pattern = re.compile(r"\b" + re.escape(s) + r"\b", re.IGNORECASE)
        candidate = _collapse(pattern.sub(" ", out))
        if not candidate:
            continue
        if len(candidate) < max(8, int(0.45 * len(out))):
            continue
        out = candidate
    return out


def strip_album_series_clause(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return text
    parts = _DASH_SEP_RE.split(text, maxsplit=1)
    if len(parts) == 2 and SERIES_ALBUM_RE.search(parts[1]):
        return parts[0].strip()
    return text


def take_after_last_dash(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return text
    for sep in (" - ", " – ", " — "):
        if sep not in text:
            continue
        head, tail = text.rsplit(sep, 1)
        head, tail = head.strip(), tail.strip()
        if not tail:
            return text
        tail_fold = _fold(tail)
        if tail_fold in _JUNK_SUBTITLE_TAILS:
            return text
        head_looks_like_path = (
            SERIES_ALBUM_RE.search(head)
            or bool(_LEADING_INDEX_PREFIX_RE.match(head))
            or head.count(" - ") >= 1
            or bool(re.search(r"\b\d{1,3}\b", head))
        )
        if head_looks_like_path and sum(
            1 for w in tail.split() if any(c.isalpha() for c in w)
        ) >= 1:
            return tail
        if len(head) >= len(tail):
            return text
    return text


def take_main_subtitle(title: str) -> str:
    main, sub = split_subtitle(title)
    if not main:
        return title
    if sub and _fold(sub) in _JUNK_SUBTITLE_TAILS:
        return title
    return main


def strip_leading_index_prefix(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return text
    for _ in range(3):
        m = _LEADING_INDEX_PREFIX_RE.match(text)
        if not m:
            break
        text = text[m.end() :].strip()
    text = re.sub(
        r"^(?:the\s+)?[a-z][\w\s'&-]{0,50}?\s+"
        r"(?:trilogy|saga|series|chronicles|cycle)\s+\d{1,3}\s*[-–—]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text


def strip_obvious_part_prefix(title: str) -> str:
    """Strip leading and trailing track/part markers from a title."""
    text = (title or "").strip()
    if not text:
        return text
    m = _LEADING_TRACK_RE.match(text)
    if m and len(m.group(1).split()) >= 2:
        text = m.group(1).strip()
    else:
        m = _INLINE_INDEX_RE.match(text)
        if m and len(m.group(1).split()) >= 2:
            text = m.group(1).strip()
    return strip_obvious_part_suffix(text)


def strip_obvious_part_suffix(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return text
    m = _PART_SUFFIX_RE.search(text)
    if not m:
        return text
    head = text[: m.start()].strip()
    if len(head.split()) < 1 or len(head) < 4:
        return text
    if len(head.split()) == 1 and len(head) < 5:
        return text
    return head


def strip_multipart_suffix(title: str) -> str:
    return _MULTIPART_SUFFIX_RE.sub("", (title or "").strip()).strip()


def strip_narrator_paren(title: str) -> str:
    return _NARRATOR_PAREN_RE.sub("", (title or "").strip()).strip()


def strip_junk_subtitle_tail(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return text
    for sep in (" - ", " – ", " — "):
        if sep not in text:
            continue
        head, tail = text.rsplit(sep, 1)
        if _fold(tail.strip()) in _JUNK_SUBTITLE_TAILS:
            return head.strip()
    return text


def strip_collection_prefix(title: str) -> str:
    return _COLLECTION_PREFIX_RE.sub("", (title or "").strip()).strip()


def _token_overlap(a: str, b: str) -> float:
    ta = set(_fold(a).split())
    tb = set(_fold(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _cleanup_is_subtractive(cleaned: str, raw_norm: str) -> bool:
    tc = set(_fold(cleaned).split())
    tr = set(_fold(raw_norm).split())
    return bool(tc) and tc <= tr


def light_title_cleanup(title: str) -> str:
    text = (title or "").strip()
    if not text:
        return ""
    text = strip_multipart_suffix(text)
    text = strip_obvious_part_prefix(text)
    text = strip_junk_subtitle_tail(text)
    text = strip_title_edges(text)
    return normalize_title(text) or text
