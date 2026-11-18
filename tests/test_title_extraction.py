"""Tests for production title extraction presets."""

from __future__ import annotations

from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.cleanup_pipeline import validate_step_ids
from stager_core.metadata.title_extraction import (
    TitleExtractionConfig,
    BALANCED_PRE,
    config_from_settings,
    extract_conservative,
    extract_title,
)
from stager_core.metadata.types import TagInfo


def _book(**kwargs) -> FlatBook:
  defaults = dict(
      id="b1",
      flatten_name="Flatten",
      source_path="/Audiobooks/Author/03 - Dune - A Novel",
      source_path_parts=["Audiobooks", "Author", "03 - Dune - A Novel"],
      top_level_pack="",
      parent_context="Author",
      grouping="folder",
      files=[AudioFile(name="03 - Dune.m4b", source="Author/03 - Dune.m4b", size_bytes=1)],
      flatten_target="",
  )
  defaults.update(kwargs)
  return FlatBook(**defaults)


def test_conservative_prefers_album_over_title():
    book = _book()
    tags = TagInfo(
        album="03 - Dune - A Novel (Unabridged)",
        title="Chapter 01",
        artist="Author",
    )
    title, source = extract_conservative(book, tags)
    assert source == "album"
    assert "Dune" in title
    assert "Unabridged" not in title


def test_conservative_cascades_when_album_invalid():
    book = _book(
        source_path="/Audiobooks/Author/The Final Empire",
        source_path_parts=["Audiobooks", "Author", "The Final Empire"],
        files=[AudioFile(name="The Final Empire.m4b", source="Author/The Final Empire.m4b", size_bytes=1)],
    )
    tags = TagInfo(album="", title="Chapter 01", artist="Author")
    title, source = extract_conservative(book, tags)
    assert source == "file_stem"
    assert "Final Empire" in title


def test_balanced_fuzzy_subset_default():
    book = _book()
    tags = TagInfo(
        album="The Final Empire",
        title="05 - The Final Empire (2 of 5)",
        artist="Sanderson",
    )
    title = extract_title(book, tags, TitleExtractionConfig(mode="balanced"))
    assert "Final Empire" in title


def test_config_from_settings_defaults_balanced():
    cfg = config_from_settings({})
    assert cfg.mode == "balanced"
    assert cfg.pre_steps == frozenset()
    assert cfg.post_steps == frozenset()


def test_config_from_settings_advanced_defaults_when_empty():
    cfg = config_from_settings({
        "title_extraction_mode": "advanced",
        "title_cleanup_pre": [],
        "title_cleanup_post": [],
    })
    assert cfg.mode == "advanced"
    assert cfg.pre_steps == BALANCED_PRE
    assert cfg.post_steps == frozenset({"colon_split", "trim_edges"})


def test_config_from_settings_advanced_steps():
    cfg = config_from_settings({
        "title_extraction_mode": "advanced",
        "title_cleanup_pre": ["edition", "colon_split"],
        "title_cleanup_post": ["junk_tail"],
    })
    assert cfg.mode == "advanced"
    assert cfg.pre_steps == frozenset({"edition", "colon_split"})
    assert cfg.post_steps == frozenset({"junk_tail"})


def test_validate_step_ids_accepts_author():
    steps = validate_step_ids(["author", "edition"])
    assert steps == frozenset({"author", "edition"})
