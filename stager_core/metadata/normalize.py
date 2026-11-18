"""Single source of truth for cleaning audiobook title/author strings.

Used both for building search hints *and* for normalizing every provider
candidate before it is fed to the scorer, so that comparisons happen on a
consistent, denoised representation.
"""

from __future__ import annotations

import html
import re

# Publishers / studios that frequently appear in an "author" tag but are not
# the actual author. Compared case-insensitively against the *cleaned* author.
KNOWN_PUBLISHERS: frozenset[str] = frozenset(
    {
        "graphic audio",
        "graphicaudio",
        "blackstone",
        "blackstone audio",
        "blackstone publishing",
        "tantor",
        "tantor audio",
        "tantor media",
        "recorded books",
        "brilliance",
        "brilliance audio",
        "audible studios",
        "audible originals",
        "audible",
        "bloomsbury",
        "macmillan",
        "macmillan audio",
        "penguin audio",
        "penguin random house",
        "random house audio",
        "harpercollins",
        "harperaudio",
        "harper audio",
        "simon & schuster audio",
        "simon and schuster audio",
        "hachette audio",
        "dreamscape",
        "dreamscape media",
        "podium audio",
        "podium publishing",
        "highbridge",
        "highbridge audio",
        "scholastic audio",
        "books on tape",
        "listening library",
        "oasis audio",
    }
)

# Edition descriptors (whole words).
_EDITION_WORDS = (
    "unabridged",
    "abridged",
    "dramatized",
    "dramatised",
    "dramatization",
    "audiobook",
    "audio book",
)
_EDITION_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _EDITION_WORDS) + r")\b",
    re.IGNORECASE,
)

# Any bracketed segment: (...), [...], {...}.
_BRACKET_RE = re.compile(r"[\(\[\{][^\(\)\[\]\{\}]*[\)\]\}]")

# Format / encoding noise.
_FORMAT_RE = re.compile(
    r"\b("
    r"\d{1,4}\s?kbps|\d{1,3}\s?k|"  # bitrate
    r"v?br|cbr|"  # bitrate mode
    r"mp3|m4b|m4a|aac|flac|ogg|opus|wav|"  # codecs/containers
    r"vbr|stereo|mono|"
    r"\d{2,3}\s?khz"  # sample rate
    r")\b",
    re.IGNORECASE,
)

# Standalone 4-digit year, often a publication-year tag.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Series markers: (Series #N), Book N, Vol. N, #N, "Series, Book N".
_SERIES_RE = re.compile(
    r"("
    r"\bbook\s*#?\d+\b|"
    r"\bvol(?:ume)?\.?\s*#?\d+\b|"
    r"\bbk\.?\s*#?\d+\b|"
    r"#\d+\b"
    r")",
    re.IGNORECASE,
)

# Leading index: 1-2 digit token followed by a separator when enough title remains.
_LEADING_INDEX_RE = re.compile(r"^\s*\d{1,2}[\s._\-]+(?P<rest>.+)$")
# Trailing zero-padded disc/track index (e.g. ``The Heroes 01``).
_TRAILING_ZERO_INDEX_RE = re.compile(r"\s+0\d{1,2}\s*$")

# Generic/structural titles that are useless as a stand-alone search query:
# chapter/track/disc/part/intro/outro/prologue/epilogue markers, optionally
# numbered. Mirrors the chapter detector used by the scorer.
_GENERIC_TITLE_RE = re.compile(
    r"^(?:chapter|ch\.?|track|trk|disc|disk|cd|part|pt\.?|section|sec\.?|"
    r"intro(?:duction)?|outro|prologue|epilogue|foreword|preface|"
    r"opening\s+credits|end\s+credits)"
    r"\b\s*#?\d*\s*$",
    re.IGNORECASE,
)
# Bare numeric / punctuation-only titles (e.g. ``01``, ``001``, ``1 - 2``).
_NUMERIC_TITLE_RE = re.compile(r"^[\d.\-_ ]+$")

_WS_RE = re.compile(r"\s+")
# Dangling separators / punctuation left after other cleanup steps.
_EDGE_TRIM_RE = re.compile(
    r"^[\s"
    r"\-–—‐‑‒−"  # hyphens / dashes / minus
    r":;,.|~"  # clause / list punctuation
    r"…"  # ellipsis
    r"\"'`´‘’“”«»‹›"  # quotes / guillemets
    r"\(\)\[\]\{\}"  # unmatched brackets
    r"/\\\*+=#@&"  # slashes and stray symbols
    r"]+|"
    r"[\s"
    r"\-–—‐‑‒−"
    r":;,.|~"
    r"…"
    r"\"'`´‘’“”«»‹›"
    r"\(\)\[\]\{\}"
    r"/\\\*+=#@&"
    r"]+$"
)
# Legacy alias used internally before strip_title_edges.
_TRIM_RE = _EDGE_TRIM_RE


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def strip_title_edges(text: str) -> str:
    """Remove dangling whitespace and separator punctuation from both ends."""
    out = _collapse(text or "")
    if not out:
        return ""
    prev = None
    while out != prev:
        prev = out
        out = _EDGE_TRIM_RE.sub("", out)
        out = _collapse(out)
    return out


def _trim_punct(text: str) -> str:
    return strip_title_edges(text)


def strip_edition(text: str) -> str:
    """Remove edition descriptors and any bracketed segments."""
    if not text:
        return ""
    out = _BRACKET_RE.sub(" ", text)
    out = _EDITION_RE.sub(" ", out)
    return _trim_punct(_collapse(out))


def strip_format_noise(text: str) -> str:
    """Remove bitrate/codec/sample-rate/year noise tokens.

    Year removal is conservative: a bare year that is the *only* remaining
    content (e.g. the title ``1984``) is kept rather than blanked out.
    """
    if not text:
        return ""
    out = _FORMAT_RE.sub(" ", text)
    year_removed = _collapse(_YEAR_RE.sub(" ", out))
    if year_removed:
        out = year_removed
    return _trim_punct(_collapse(out))


def strip_series_markers(text: str) -> str:
    """Remove inline series markers like ``Book 3``, ``Vol. 2``, ``#1``."""
    if not text:
        return ""
    out = _SERIES_RE.sub(" ", text)
    return _trim_punct(_collapse(out))


def _alpha_word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text) if re.search(r"[A-Za-z]", w)])


def strip_trailing_index(text: str) -> str:
    """Conservatively drop a trailing zero-padded index (``Title 01``)."""
    text = (text or "").strip()
    if not text:
        return text
    match = _TRAILING_ZERO_INDEX_RE.search(text)
    if not match:
        return text
    head = text[: match.start()].strip()
    if _alpha_word_count(head) >= 2:
        return head
    return text


def strip_leading_index(text: str) -> str:
    """Conservatively drop a leading track/disc index.

    Only strips a 1-2 digit token followed by a separator when at least two
    alphabetic words remain. Leaves intact things like ``1984``, ``1177 B.C.``,
    ``Catch-22`` and ``10th Mountain Division``.
    """
    if not text:
        return ""
    match = _LEADING_INDEX_RE.match(text)
    if not match:
        return text.strip()
    rest = match.group("rest").strip()
    if _alpha_word_count(rest) >= 2:
        return rest
    return text.strip()


def split_subtitle(title: str) -> tuple[str, str]:
    """Split ``Main: Subtitle`` (or ``Main - Subtitle``) into parts."""
    if not title:
        return "", ""
    for sep in (": ", " - ", " — ", " – "):
        idx = title.find(sep)
        if idx > 0:
            main = title[:idx].strip()
            sub = title[idx + len(sep):].strip()
            if main and sub:
                return main, sub
    return title.strip(), ""


def is_publisher_name(author: str) -> bool:
    """True when ``author`` is a known publisher/studio rather than a person."""
    if not author:
        return False
    cleaned = _trim_punct(_collapse(_BRACKET_RE.sub(" ", author))).lower()
    cleaned = re.sub(r"[.,]", "", cleaned).strip()
    return cleaned in KNOWN_PUBLISHERS


def clean_author(author: str) -> str:
    """Clean an author string.

    - Drops narrator-in-parens and any bracketed segment.
    - Returns ``""`` when the value is a known publisher/studio.
    - Collapses whitespace.
    """
    if not author:
        return ""
    if is_publisher_name(author):
        return ""
    out = _BRACKET_RE.sub(" ", author)
    out = _trim_punct(_collapse(out))
    if is_publisher_name(out):
        return ""
    return out


def normalize_title(title: str) -> str:
    """Full title normalization pipeline used before scoring/searching."""
    if not title:
        return ""
    out = strip_edition(title)
    out = strip_format_noise(out)
    out = strip_series_markers(out)
    out = strip_leading_index(out)
    return _trim_punct(_collapse(out))


def provider_text(value: str) -> str:
    """Decode HTML entities from provider payloads (e.g. MAM ``&#039;`` apostrophes)."""
    return html.unescape((value or "").strip())


def normalize_author(author: str) -> str:
    """Full author normalization pipeline (clean + denoise)."""
    cleaned = clean_author(author)
    if not cleaned:
        return ""
    cleaned = strip_format_noise(cleaned)
    return _trim_punct(_collapse(cleaned))


def is_generic_title(title: str) -> bool:
    """True when a title is too generic to use as a stand-alone search query.

    Catches structural/junk titles (``Intro``, ``Outro``, ``Chapter 3``,
    ``Track 01``), pure-number titles (``01``, ``001``), and very short tokens
    (length <= 2). Evaluated on the normalized title so denoising is applied
    first. A title-only search built from such a value matches everything and
    should be skipped.
    """
    candidate = normalize_title(title) if title else ""
    if not candidate:
        candidate = (title or "").strip()
    if not candidate:
        return True
    if len(candidate) <= 2:
        return True
    if _GENERIC_TITLE_RE.match(candidate):
        return True
    if _NUMERIC_TITLE_RE.match(candidate):
        return True
    return False
