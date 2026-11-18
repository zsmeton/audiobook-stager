from __future__ import annotations

import os
import re
from pathlib import Path

from stager_core.media_kind import AUDIOBOOK, get_kind
from stager_core.metadata.types import TagInfo

# Audible ASIN shape: 10 chars, leading B, plus the trailing 9 alphanumerics.
# A real ASIN always contains digits (e.g. B0024CEZGG); all-letter matches like
# "BLACKSTONE" / "BLOOMSBURY" / "BUCKINGHAM" are rejected by the digit check.
ASIN_RE = re.compile(r"\b(B[0-9A-Z]{9})\b", re.IGNORECASE)
_MIN_ASIN_DIGITS = 2

# Tag fields we trust to carry an ASIN. Arbitrary free-text tags are NOT scanned
# (that produced false positives like BLACKSTONE matching the loose shape).
_ASIN_FIELD_HINTS = ("asin", "audible")
_ASIN_TEXT_FIELDS = ("comment", "description")
CHAPTER_TITLE_RE = re.compile(
    r"^(?:chapter|ch\.?|track|disc|disk|cd|part|pt\.?)\s*#?\d+",
    re.IGNORECASE,
)
SERIES_ALBUM_RE = re.compile(r"\b(?:bk\.?|book|vol\.?|volume|#\d+)\b", re.IGNORECASE)


def _first(tags: dict, *keys: str) -> str:
    for key in keys:
        val = tags.get(key)
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            if val:
                return str(val[0]).strip()
        elif str(val).strip():
            return str(val).strip()
    return ""


def _is_valid_asin(candidate: str) -> bool:
    if len(candidate) != 10 or candidate[0].upper() != "B":
        return False
    return sum(ch.isdigit() for ch in candidate) >= _MIN_ASIN_DIGITS


def extract_asin(text: str) -> str:
    if not text:
        return ""
    for match in ASIN_RE.finditer(text.upper()):
        candidate = match.group(1).upper()
        if _is_valid_asin(candidate):
            return candidate
    return ""


def _values_for_key(tags: dict, key: str) -> list[str]:
    val = tags.get(key)
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(v) for v in val]
    return [str(val)]


def _extract_asin_from_trusted_fields(tags: dict, comment: str) -> str:
    """Only look for an ASIN in explicit ASIN/audible/comment fields."""
    asin = extract_asin(comment)
    if asin:
        return asin
    for key, value in tags.items():
        key_l = str(key).lower()
        if any(hint in key_l for hint in _ASIN_FIELD_HINTS):
            for item in (value if isinstance(value, (list, tuple)) else [value]):
                found = extract_asin(str(item))
                if found:
                    return found
    for field_name in _ASIN_TEXT_FIELDS:
        for item in _values_for_key(tags, field_name):
            found = extract_asin(item)
            if found:
                return found
    return ""


def read_tags(path: Path) -> TagInfo:
    return get_kind(AUDIOBOOK).read_tags(path)


def read_audiobook_tags(path: Path) -> TagInfo:
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return TagInfo()

    if not path.is_file():
        return TagInfo()

    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        return TagInfo()
    if audio is None:
        return TagInfo()

    tags = dict(audio.tags or {})
    title = _first(tags, "title")
    album = _first(tags, "album")
    artist = _first(tags, "artist", "albumartist")
    albumartist = _first(tags, "albumartist", "artist")
    narrator = _first(tags, "composer", "performer")
    comment = _first(tags, "comment", "description")

    asin = _extract_asin_from_trusted_fields(tags, comment)

    return TagInfo(
        title=title,
        album=album or title,
        artist=artist or albumartist,
        albumartist=albumartist or artist,
        asin=asin,
        narrator=narrator,
        raw={k: (v[0] if isinstance(v, list) and v else v) for k, v in tags.items()},
    )


def read_book_tags(source_root: Path, file_sources: list[str]) -> TagInfo:
    merged = TagInfo()
    for rel in file_sources:
        path = source_root / rel.replace("/", os.sep)
        info = read_tags(path)
        if not merged.title and info.title:
            merged.title = info.title
        if not merged.album and info.album:
            merged.album = info.album
        if not merged.artist and info.artist:
            merged.artist = info.artist
        if not merged.albumartist and info.albumartist:
            merged.albumartist = info.albumartist
        if not merged.asin and info.asin:
            merged.asin = info.asin
        if not merged.narrator and info.narrator:
            merged.narrator = info.narrator
        merged.raw.update(info.raw)
    return merged


def _best_id3_title(tags: TagInfo) -> str:
    title = (tags.title or "").strip()
    album = (tags.album or "").strip()
    if not title:
        return album
    if not album or title.lower() == album.lower():
        return title
    if CHAPTER_TITLE_RE.match(title):
        return album
    if SERIES_ALBUM_RE.search(album) and not SERIES_ALBUM_RE.search(title):
        return title
    return title


def tag_candidate(tags: TagInfo) -> "MetadataCandidate | None":
    from stager_core.metadata.types import MetadataCandidate

    author = tags.artist or tags.albumartist
    title = _best_id3_title(tags)
    if not author and not title:
        return None
    # Confidence is owned by the scorer now; providers/local tiers return 0.0.
    return MetadataCandidate(
        author=author or "Unknown Author",
        title=title or "Untitled",
        source="id3",
        confidence=0.0,
        narrator=tags.narrator or "",
        asin=tags.asin or "",
        raw=tags.to_dict(),
    )
