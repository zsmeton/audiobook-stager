from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.library_vocab import LibraryVocabulary
from stager_core.metadata.lvi import (
    annotate_candidates_lvi,
    apply_lvi_search,
    library_corroboration_evidence,
    resolve_lvi_form_match,
    resolve_lvi_match,
)
from stager_core.metadata.normalize import provider_text
from stager_core.metadata.scoring import source_prior
from stager_core.metadata.tags import TagInfo
from stager_core.metadata.types import MetadataCandidate


def _lvi_row(book_id: str, author: str, title: str = "Book One") -> dict:
    return {
        "book_id": book_id,
        "staged": True,
        "db_status": "staged",
        "ground_truth": {
            "author": author,
            "title": title,
            "series": "",
            "series_index": "",
            "staged_path": f"{author}/{title}",
            "source": "author:parsed",
        },
        "chosen_author": author,
        "chosen_series": "",
    }


def _flat_book(author_dir: str, title: str = "New Book") -> FlatBook:
    return FlatBook(
        id="seed1",
        source_path=f"{author_dir}/{title}",
        source_path_parts=[author_dir, title],
        top_level_pack=author_dir,
        parent_context="",
        grouping="folder",
        flatten_name=title,
        flatten_target=f"{author_dir}/{title}",
        files=[AudioFile(name=f"{title}.m4b", source=f"{title}.m4b", size_bytes=1000)],
    )


class TestLviLookup:
    def test_resolve_lvi_match_from_id3_hint(self) -> None:
        lvi = LibraryVocabulary.build_from_rows([
            _lvi_row("b1", "Brandon Sanderson", "Mistborn"),
        ])
        book = _flat_book("Sanderson", "The Final Empire")
        tags = TagInfo(artist="Sanderson", album="The Final Empire")
        match = resolve_lvi_match(lvi, book, tags)
        assert match.author_hit
        assert match.author == "Brandon Sanderson"

    def test_apply_lvi_search_replace_only_when_enabled(self) -> None:
        from stager_core.metadata.lvi import LviMatch

        ctx = {"author": "Sanderson", "title": "Mistborn"}
        m = LviMatch(author="Brandon Sanderson", author_hit=True)
        apply_lvi_search(ctx, m, enabled=True)
        assert ctx["author"] == "Brandon Sanderson"
        assert ctx["raw_author"] == "Sanderson"
        ctx2 = {"author": "Sanderson", "title": "Mistborn"}
        apply_lvi_search(ctx2, m, enabled=False)
        assert ctx2["author"] == "Sanderson"

    def test_library_corroboration_evidence(self) -> None:
        lvi = LibraryVocabulary.build_from_rows([_lvi_row("b1", "Brandon Sanderson")])
        cands = [
            MetadataCandidate(
                author="Brandon Sanderson",
                title="The Final Empire",
                source="audible",
                confidence=0.0,
            ),
            MetadataCandidate(
                author="Unknown Author",
                title="Other",
                source="audible",
                confidence=0.0,
            ),
        ]
        annotate_candidates_lvi(cands, lvi)
        evidence = library_corroboration_evidence(cands)
        assert len(evidence) == 1
        assert evidence[0].source == "library"
        assert source_prior("library") == 0.80

    def test_compound_author_not_in_library(self) -> None:
        lvi = LibraryVocabulary.build_from_rows([_lvi_row("b1", "Cixin Liu")])
        cands = [
            MetadataCandidate(
                author="Cixin Liu, Joel Martinsen - translator",
                title="The Dark Forest",
                series="The Remembrance of Earth's Past #2",
                source="audible",
                confidence=0.0,
            ),
        ]
        annotate_candidates_lvi(cands, lvi)
        assert not cands[0].lvi_in_library
        assert not cands[0].lvi_author_matched
        assert len(library_corroboration_evidence(cands)) == 0

    def test_exact_author_gets_library_boost(self) -> None:
        lvi = LibraryVocabulary.build_from_rows([_lvi_row("b1", "Cixin Liu")])
        cands = [
            MetadataCandidate(
                author="Cixin Liu",
                title="The Dark Forest",
                source="audible",
                confidence=0.0,
            ),
        ]
        annotate_candidates_lvi(cands, lvi)
        assert cands[0].lvi_in_library
        assert len(library_corroboration_evidence(cands)) == 1

    def test_series_exact_uses_filesystem_key(self) -> None:
        from stager_core.metadata.library_vocab import author_key, series_key
        from stager_core.metadata.normalize import provider_text

        series = "Remembrance of Earth's Past"
        row = _lvi_row("b1", "Cixin Liu", "The Three-Body Problem")
        row["ground_truth"]["series"] = series
        row["ground_truth"]["staged_path"] = f"Cixin Liu/{series}/1 - The Three-Body Problem"
        row["chosen_series"] = series
        lvi = LibraryVocabulary.build_from_rows([row])
        akey = author_key("Cixin Liu")
        assert series_key(series) in lvi.series_by_author[akey]
        assert lvi.match_series_exact(series, akey) is not None
        assert lvi.match_series_exact("The Remembrance of Earth's Past #2", akey) is None
        assert lvi.match_series_exact("Remembrance of Earths Past", akey) is None

    def test_mam_html_entity_series_gets_lvi_chrome(self) -> None:
        from stager_core.metadata.library_vocab import author_key

        series = "Remembrance of Earth's Past"
        row = _lvi_row("b1", "Cixin Liu", "The Three-Body Problem")
        row["ground_truth"]["series"] = series
        row["ground_truth"]["staged_path"] = f"Cixin Liu/{series}/1 - The Three-Body Problem"
        row["chosen_series"] = series
        lvi = LibraryVocabulary.build_from_rows([row])
        cands = [
            MetadataCandidate(
                author="Cixin Liu",
                title="The Dark Forest",
                series="Remembrance of Earth&#039;s Past",
                series_index="2",
                source="mam",
                confidence=0.0,
            ),
        ]
        annotate_candidates_lvi(cands, lvi)
        assert cands[0].lvi_series_matched
        assert provider_text(cands[0].series) == series

    def test_resolve_lvi_form_match_manual_fields(self) -> None:
        series = "Remembrance of Earth's Past"
        row = _lvi_row("b1", "Cixin Liu", "The Three-Body Problem")
        row["ground_truth"]["series"] = series
        row["ground_truth"]["staged_path"] = f"Cixin Liu/{series}/1 - The Three-Body Problem"
        row["chosen_series"] = series
        lvi = LibraryVocabulary.build_from_rows([row])
        m = resolve_lvi_form_match(lvi, "Cixin Liu", series)
        assert m.author_matched
        assert m.series_matched
        assert m.series == series
        m2 = resolve_lvi_form_match(lvi, "Cixin Liu", "The Remembrance of Earth's Past #2")
        assert m2.author_matched
        assert not m2.series_matched

    def test_refresh_candidates_lvi_updates_stale_flags(self) -> None:
        from stager_core.metadata.lvi import refresh_candidates_lvi

        series = "Remembrance of Earth's Past"
        row = _lvi_row("b1", "Cixin Liu", "The Three-Body Problem")
        row["ground_truth"]["series"] = series
        row["ground_truth"]["staged_path"] = f"Cixin Liu/{series}/1 - The Three-Body Problem"
        row["chosen_series"] = series
        lvi = LibraryVocabulary.build_from_rows([row])
        stored = [
            {
                "author": "Cixin Liu",
                "title": "The Dark Forest",
                "source": "mam",
                "confidence": 0.0,
                "series": "Remembrance of Earth&#039;s Past",
                "series_index": "2",
                "lvi_author_matched": False,
                "lvi_series_matched": False,
                "lvi_in_library": False,
            }
        ]
        refreshed = refresh_candidates_lvi(stored, lvi)
        assert refreshed[0]["lvi_author_matched"]
        assert refreshed[0]["lvi_series_matched"]
        assert refreshed[0]["lvi_in_library"]

    def test_exclude_book_id_from_vocab(self) -> None:
        rows = [
            _lvi_row("a1", "Brandon Sanderson", "Book A"),
            _lvi_row("a2", "Brandon Sanderson", "Book B"),
        ]
        lvi = LibraryVocabulary.build_from_rows(rows, exclude_book_ids={"a1"})
        assert lvi.summary()["n_books"] == 1
