"""Title extraction presets for metadata lookup."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

from stager_core.discovery import FlatBook, stem_base
from stager_core.metadata.cleanup_pipeline import (
    ADVANCED_UI_STEPS,
    apply_contextual_steps,
    fuzzy_subset_with_cleanup,
    validate_step_ids,
)
from stager_core.metadata.normalize import strip_title_edges
from stager_core.metadata.title_matching import (
    eligible_title,
    fuzzy_subset_title,
    path_deepest_segment,
)
from stager_core.metadata.types import TagInfo

TitleExtractionMode = Literal["conservative", "balanced", "advanced"]

CONSERVATIVE_STEPS = frozenset({
    "edition",
    "part_prefix",
    "format_noise",
    "leading_index",
    "colon_split",
    "series_name",
    "trim_edges",
})
BALANCED_PRE = CONSERVATIVE_STEPS
ADVANCED_DEFAULT_PRE = BALANCED_PRE
ADVANCED_DEFAULT_POST = frozenset({"colon_split", "trim_edges"})
ADVANCED_STEPS = frozenset(ADVANCED_UI_STEPS)

CONSERVATIVE_SOURCES = ("album", "id3_title", "file_stem", "path_deepest")


def resolve_advanced_steps(
    pre_raw: list[str] | None,
    post_raw: list[str] | None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Advanced preset: balanced pre cleanup + colon_split post when unset."""
    pre_list = pre_raw if isinstance(pre_raw, list) else []
    post_list = post_raw if isinstance(post_raw, list) else []
    if not pre_list and not post_list:
        return ADVANCED_DEFAULT_PRE, ADVANCED_DEFAULT_POST
    return validate_step_ids(pre_list), validate_step_ids(post_list)


@dataclass(frozen=True)
class TitleExtractionConfig:
    mode: TitleExtractionMode = "balanced"
    pre_steps: frozenset[str] = frozenset()
    post_steps: frozenset[str] = frozenset()


def config_from_settings(settings: dict[str, Any]) -> TitleExtractionConfig:
    mode = (settings.get("title_extraction_mode") or "balanced").strip().lower()
    if mode not in ("conservative", "balanced", "advanced"):
        mode = "balanced"
    pre_raw = settings.get("title_cleanup_pre") or []
    post_raw = settings.get("title_cleanup_post") or []
    if mode == "advanced":
        pre, post = resolve_advanced_steps(pre_raw, post_raw)
    else:
        pre, post = frozenset(), frozenset()
    return TitleExtractionConfig(mode=mode, pre_steps=pre, post_steps=post)


def _conservative_sources(book: FlatBook, tags: TagInfo) -> list[tuple[str, str]]:
    stem = ""
    if book.files:
        stem = stem_base(book.files[0].name.rsplit(".", 1)[0])
    return [
        ("album", (tags.album or "").strip()),
        ("id3_title", (tags.title or "").strip()),
        ("file_stem", stem),
        ("path_deepest", path_deepest_segment(book)),
    ]


def extract_conservative(book: FlatBook, tags: TagInfo) -> tuple[str, str]:
    """Cascade album → title → file_stem → path; return (title, source_used)."""
    for source, raw in _conservative_sources(book, tags):
        cleaned = apply_contextual_steps(raw, CONSERVATIVE_STEPS, book, tags)
        if cleaned and eligible_title(cleaned):
            return cleaned, source
    return "", ""


def extract_balanced(book: FlatBook, tags: TagInfo) -> tuple[str, str]:
    preclean = partial(apply_contextual_steps, steps=BALANCED_PRE, book=book, tags=tags)

    def postclean(raw: str) -> str:
        return strip_title_edges(raw)

    title = fuzzy_subset_title(book, tags, preclean=preclean, postclean=postclean)
    return title, "fuzzy_subset"


def extract_advanced(book: FlatBook, tags: TagInfo, config: TitleExtractionConfig) -> tuple[str, str]:
    title = fuzzy_subset_with_cleanup(
        book,
        tags,
        config.pre_steps,
        config.post_steps,
        post_guard=False,
    )
    return title, "fuzzy_subset_advanced"


def extract_title(
    book: FlatBook,
    tags: TagInfo,
    config: TitleExtractionConfig | None = None,
) -> str:
    """Resolve a search title from book tags and path using the configured strategy."""
    cfg = config or TitleExtractionConfig()
    if cfg.mode == "conservative":
        title, _ = extract_conservative(book, tags)
        return title
    if cfg.mode == "advanced":
        title, _ = extract_advanced(book, tags, cfg)
        return title
    title, _ = extract_balanced(book, tags)
    return title


def extract_title_with_source(
    book: FlatBook,
    tags: TagInfo,
    config: TitleExtractionConfig | None = None,
) -> tuple[str, str]:
    """Like extract_title but returns (title, source_label) for previews."""
    cfg = config or TitleExtractionConfig()
    if cfg.mode == "conservative":
        return extract_conservative(book, tags)
    if cfg.mode == "advanced":
        return extract_advanced(book, tags, cfg)
    return extract_balanced(book, tags)
