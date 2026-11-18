"""Composable pre/post cleanup groups for fuzzy subset title extraction."""

from __future__ import annotations

from stager_core.discovery import FlatBook, stem_base
from stager_core.metadata.normalize import (
    is_generic_title,
    normalize_title,
    strip_edition,
    strip_format_noise,
    strip_leading_index,
    strip_series_markers,
    strip_title_edges,
    strip_trailing_index,
)
from stager_core.metadata.title_cleanup import (
    _cleanup_is_subtractive,
    _token_overlap,
    author_hints,
    series_hints,
    strip_album_series_clause,
    strip_author_prefix,
    strip_by_author_suffix,
    strip_collection_prefix,
    strip_junk_subtitle_tail,
    strip_leading_index_prefix,
    strip_multipart_suffix,
    strip_narrator_paren,
    strip_obvious_part_prefix,
    strip_series_book_suffix,
    strip_series_name,
    take_after_last_dash,
    take_main_subtitle,
)
from stager_core.metadata.title_matching import fuzzy_subset_title
from stager_core.metadata.types import TagInfo

PRE_STEP_ORDER: tuple[str, ...] = (
    "multipart",
    "part_prefix",
    "junk_tail",
    "edition",
    "format_noise",
    "series_markers",
    "leading_index",
    "index_trailing",
)

POST_STEP_ORDER: tuple[str, ...] = (
    "multipart",
    "part_prefix",
    "junk_tail",
    "index_prefix",
    "dash_after",
    "colon_split",
    "author",
    "narrator",
    "edition",
    "format_noise",
    "series_markers",
    "leading_index",
    "index_trailing",
    "collection_prefix",
    "album_series_clause",
    "series_book_suffix",
    "series_name",
    "trim_edges",
)

POST_FACTORIAL_ORDER: tuple[str, ...] = tuple(
    s for s in POST_STEP_ORDER if s not in ("multipart", "part_prefix", "junk_tail")
)

NORMALIZE_SUBSTEPS: frozenset[str] = frozenset(
    {"edition", "format_noise", "series_markers", "leading_index"}
)

ADVANCED_UI_STEPS: tuple[str, ...] = (
    "edition",
    "part_prefix",
    "format_noise",
    "leading_index",
    "index_trailing",
    "colon_split",
    "series_name",
    "author",
    "junk_tail",
    "multipart",
    "series_markers",
    "trim_edges",
)

CONTEXTUAL_STEP_ORDER: tuple[str, ...] = PRE_STEP_ORDER + (
    "colon_split",
    "series_name",
    "trim_edges",
)

_LEGACY_NORMALIZE = "normalize"

_ALL_PRE_ATOMIC = frozenset(PRE_STEP_ORDER)
LIGHT_PRE = frozenset(PRE_STEP_ORDER)
POST_LIGHT_STEPS = frozenset(
    {"multipart", "part_prefix", "junk_tail", *NORMALIZE_SUBSTEPS, "author", "narrator"}
)

# Legacy private aliases for research shims.
_LIGHT_PRE = LIGHT_PRE
_POST_LIGHT_STEPS = POST_LIGHT_STEPS


def expand_step_ids(groups: frozenset[str] | set[str]) -> frozenset[str]:
    """Expand legacy ``normalize`` alias to all four atomic substeps."""
    out: set[str] = set()
    for step in groups:
        if step == _LEGACY_NORMALIZE:
            out.update(NORMALIZE_SUBSTEPS)
        else:
            out.add(step)
    return frozenset(out)


def _apply_normalize_substep(text: str, step: str) -> str:
    if step == "edition":
        return strip_edition(text)
    if step == "format_noise":
        return strip_format_noise(text)
    if step == "series_markers":
        return strip_series_markers(text)
    if step == "leading_index":
        return strip_leading_index(text)
    if step == _LEGACY_NORMALIZE:
        return normalize_title(text) or text
    raise ValueError(f"unknown normalize substep: {step}")


def _apply_pre_step(text: str, step: str) -> str:
    if step == "multipart":
        return strip_multipart_suffix(text)
    if step == "part_prefix":
        return strip_obvious_part_prefix(text)
    if step == "junk_tail":
        return strip_junk_subtitle_tail(text)
    if step in NORMALIZE_SUBSTEPS or step == _LEGACY_NORMALIZE:
        return _apply_normalize_substep(text, step)
    if step == "index_trailing":
        return strip_trailing_index(text)
    raise ValueError(f"unknown pre step: {step}")


def _apply_post_step(text: str, step: str, book: FlatBook, tags: TagInfo) -> str:
    if step == "multipart":
        return strip_multipart_suffix(text)
    if step == "part_prefix":
        return strip_obvious_part_prefix(text)
    if step == "junk_tail":
        return strip_junk_subtitle_tail(text)
    if step == "index_prefix":
        return strip_leading_index_prefix(text)
    if step == "dash_after":
        return take_after_last_dash(text)
    if step == "colon_split":
        return take_main_subtitle(text)
    if step == "author":
        authors = author_hints(book, tags)
        text = strip_author_prefix(text, authors)
        return strip_by_author_suffix(text, authors)
    if step == "narrator":
        return strip_narrator_paren(text)
    if step in NORMALIZE_SUBSTEPS or step == _LEGACY_NORMALIZE:
        return _apply_normalize_substep(text, step)
    if step == "collection_prefix":
        return strip_collection_prefix(text)
    if step == "album_series_clause":
        return strip_album_series_clause(text)
    if step == "series_book_suffix":
        return strip_series_book_suffix(text)
    if step == "series_name":
        return strip_series_name(text, series_hints(book, tags))
    if step == "trim_edges":
        return strip_title_edges(text)
    if step == "index_trailing":
        return strip_trailing_index(text)
    raise ValueError(f"unknown post step: {step}")


def apply_pre_groups(text: str, groups: frozenset[str]) -> str:
    """Apply selected pre-LCS cleanup steps in canonical order."""
    out = (text or "").strip()
    if not out:
        return ""
    expanded = expand_step_ids(groups)
    for step in PRE_STEP_ORDER:
        if step in expanded:
            out = _apply_pre_step(out, step)
    return out


def apply_contextual_steps(
    text: str,
    steps: frozenset[str] | set[str],
    book: FlatBook,
    tags: TagInfo,
) -> str:
    """Apply pre-atomic and context-aware steps (colon_split, series_name) in order."""
    out = (text or "").strip()
    if not out:
        return ""
    expanded = expand_step_ids(steps)
    for step in CONTEXTUAL_STEP_ORDER:
        if step not in expanded:
            continue
        if step in PRE_STEP_ORDER:
            out = _apply_pre_step(out, step)
        elif step == "colon_split":
            out = take_main_subtitle(out)
        elif step == "series_name":
            out = strip_series_name(out, series_hints(book, tags))
        elif step == "trim_edges":
            out = strip_title_edges(out)
        elif step == "index_trailing":
            out = strip_trailing_index(out)
    for step in ("author", "narrator"):
        if step in expanded:
            out = _apply_post_step(out, step, book, tags)
    return out.strip()


def apply_post_groups(
    text: str,
    book: FlatBook,
    tags: TagInfo,
    groups: frozenset[str],
    *,
    guard: bool = False,
) -> str:
    """Apply selected post-LCS cleanup steps; optional subtractive guard wrapper."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if not groups and not guard:
        return raw

    expanded = expand_step_ids(groups)
    out = raw
    for step in POST_STEP_ORDER:
        if step in expanded:
            out = _apply_post_step(out, step, book, tags)

    if not guard:
        return out

    raw_norm = apply_pre_groups(raw, _LIGHT_PRE) or raw
    stem_norm = _stem_norm_light(book)
    return _guard_post_output(raw, out, book, raw_norm=raw_norm, stem_norm=stem_norm)


def _stem_norm_light(book: FlatBook) -> str:
    if not book.files:
        return ""
    return apply_pre_groups(
        stem_base(book.files[0].name.rsplit(".", 1)[0]),
        _LIGHT_PRE,
    )


def _guard_post_output(
    raw: str,
    cleaned: str,
    book: FlatBook,
    *,
    raw_norm: str,
    stem_norm: str,
) -> str:
    if not cleaned:
        return stem_norm or raw_norm

    if is_generic_title(cleaned):
        return stem_norm or raw_norm

    if _cleanup_is_subtractive(cleaned, raw_norm):
        return cleaned

    overlap = _token_overlap(cleaned, stem_norm or raw_norm)
    if overlap < 0.25 or len(cleaned) < max(4, int(0.35 * len(raw_norm))):
        return stem_norm or raw_norm

    return cleaned


def _groups_label(prefix: str, groups: frozenset[str], order: tuple[str, ...]) -> str:
    if not groups:
        return f"{prefix}:none"
    parts = [g for g in order if g in groups]
    return f"{prefix}:{'+'.join(parts)}"


def strategy_label(
    pre_groups: frozenset[str],
    post_groups: frozenset[str],
    *,
    post_guard: bool = False,
    name: str | None = None,
) -> str:
    if name:
        return name
    pre = _groups_label("pre", expand_step_ids(pre_groups), PRE_STEP_ORDER)
    post = _groups_label("post", expand_step_ids(post_groups), POST_STEP_ORDER)
    guard = "+guard" if post_guard else ""
    return f"{pre}|{post}{guard}"


def fuzzy_subset_with_cleanup(
    book: FlatBook,
    tags: TagInfo,
    pre_groups: frozenset[str],
    post_groups: frozenset[str],
    *,
    post_guard: bool = False,
) -> str:
    """fuzzy_subset_title with composable pre/post cleanup groups."""
    pre_expanded = expand_step_ids(pre_groups)
    post_expanded = expand_step_ids(post_groups)

    def preclean(value: str) -> str:
        if not pre_expanded:
            return (value or "").strip()
        return apply_contextual_steps(value, pre_expanded, book, tags)

    use_post = bool(post_expanded) or post_guard

    def postclean(raw: str) -> str:
        return apply_post_groups(
            raw,
            book,
            tags,
            post_expanded,
            guard=post_guard,
        )

    return fuzzy_subset_title(
        book,
        tags,
        preclean=preclean,
        postclean=postclean if use_post else None,
    )


def fuzzy_subset_pre_only(
    book: FlatBook,
    tags: TagInfo,
    pre_groups: frozenset[str],
) -> str:
    """Run fuzzy_subset with pre cleanup only; returns raw LCS consensus string."""
    return fuzzy_subset_with_cleanup(book, tags, pre_groups, frozenset(), post_guard=False)


def evaluate_post_on_cached_raw(
    raw: str,
    book: FlatBook,
    tags: TagInfo,
    post_groups: frozenset[str],
    *,
    post_guard: bool = False,
) -> str:
    """Apply post-LCS cleanup to a cached pre-only fuzzy result."""
    if not post_groups and not post_guard:
        return raw
    return apply_post_groups(raw, book, tags, post_groups, guard=post_guard)


def validate_step_ids(steps: list[str] | set[str]) -> frozenset[str]:
    """Validate and return a frozenset of known advanced UI step ids."""
    allowed = frozenset(ADVANCED_UI_STEPS)
    out: set[str] = set()
    for step in steps:
        s = (step or "").strip()
        if not s:
            continue
        if s not in allowed:
            raise ValueError(f"unknown title cleanup step: {s}")
        out.add(s)
    return frozenset(out)
