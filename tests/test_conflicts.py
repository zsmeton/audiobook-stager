from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.conflicts import (
    LIBRARY_SIDE_ID,
    book_target_key,
    build_library_index,
    classify_conflict_kind,
    detect_conflict_groups,
    pick_default_winner,
    resolve_winner_metadata,
    summarize_files,
)
from stager_core.staging import build_inode_index
from stager_core.staging import compute_target_key


def _seed_row(
    book_id: str,
    author: str,
    title: str,
    *,
    source_path: str,
    file_source: str,
    file_name: str,
    size_bytes: int,
    confidence: float = 0.5,
) -> dict:
    return {
        "id": book_id,
        "status": "pending",
        "chosen_author": author,
        "chosen_title": title,
        "chosen_author_set": 1 if author else 0,
        "chosen_title_set": 1 if title else 0,
        "chosen_series_set": 0,
        "chosen_series_index_set": 0,
        "suggested_author": "",
        "suggested_title": "",
        "suggested_series": "",
        "suggested_series_state": "unknown",
        "flatten_name": title,
        "source_path": source_path,
        "confidence": confidence,
        "files": [{"name": file_name, "source": file_source, "size_bytes": size_bytes}],
        "tags": {},
        "candidates": [],
    }


class ConflictTests(unittest.TestCase):
    def test_compute_target_key_sanitizes(self) -> None:
        key = compute_target_key("Author: Name", "Title/Sub")
        self.assertNotIn(":", key)
        title_part = key.split("/", 1)[1]
        self.assertNotIn("/", title_part)
        self.assertIn("/", key)

    def test_two_seeds_same_target(self) -> None:
        rows = [
            _seed_row("a", "Author", "Title", source_path="seed/a", file_source="a/a.mp3", file_name="a.mp3", size_bytes=1000),
            _seed_row("b", "Author", "Title", source_path="seed/b", file_source="b/b.m4b", file_name="b.m4b", size_bytes=500, confidence=0.6),
        ]
        groups, conflict_ids = detect_conflict_groups(
            rows, Path("/nonexistent/lib"), Path("/nonexistent/src"), {}, {}, {}
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(conflict_ids, {"a", "b"})
        self.assertEqual(groups[0]["winner_side_id"], "b")
        self.assertEqual(groups[0]["default_winner_side_id"], "b")
        self.assertEqual(groups[0]["conflict_kind"], "pending")

    def test_classify_conflict_kind(self) -> None:
        self.assertEqual(classify_conflict_kind(has_library=False, seed_count=2), "pending")
        self.assertEqual(classify_conflict_kind(has_library=True, seed_count=1), "staged")
        self.assertEqual(classify_conflict_kind(has_library=True, seed_count=2), "mixed")

    def test_pick_default_winner_prefers_library(self) -> None:
        m4b = summarize_files([{"name": "book.m4b", "size_bytes": 50}])
        lib = summarize_files([{"name": "existing.mp3", "size_bytes": 900}])
        sides = [
            {
                "side_id": "seed1",
                "type": "seed",
                "file_count": m4b["file_count"],
                "total_size_bytes": m4b["total_size_bytes"],
                "dominant_format": m4b["dominant_format"],
                "confidence": 0.95,
            },
            {
                "side_id": LIBRARY_SIDE_ID,
                "type": "library",
                "file_count": lib["file_count"],
                "total_size_bytes": lib["total_size_bytes"],
                "dominant_format": lib["dominant_format"],
                "confidence": 1.0,
            },
        ]
        self.assertEqual(pick_default_winner(sides), LIBRARY_SIDE_ID)

    def test_excludes_staged_and_partial(self) -> None:
        rows = [
            {"id": "s", "status": "staged", "chosen_author": "A", "chosen_title": "T",
             "suggested_author": "", "suggested_title": "", "flatten_name": "",
             "files": [], "tags": {}, "candidates": []},
            {"id": "p", "status": "partial_staged", "chosen_author": "A", "chosen_title": "T",
             "suggested_author": "", "suggested_title": "", "flatten_name": "",
             "files": [], "tags": {}, "candidates": []},
        ]
        groups, conflict_ids = detect_conflict_groups(
            rows, Path("/lib"), Path("/src"), {}, {}, {}
        )
        self.assertEqual(groups, [])
        self.assertEqual(conflict_ids, set())

    def test_format_scoring_prefers_m4b(self) -> None:
        m4b = summarize_files([{"name": "book.m4b", "size_bytes": 900}])
        mp3 = summarize_files([{"name": "book.mp3", "size_bytes": 100}])
        sides = [
            {"side_id": "mp3", "file_count": mp3["file_count"], "total_size_bytes": mp3["total_size_bytes"],
             "dominant_format": mp3["dominant_format"], "confidence": 0.9},
            {"side_id": "m4b", "file_count": m4b["file_count"], "total_size_bytes": m4b["total_size_bytes"],
             "dominant_format": m4b["dominant_format"], "confidence": 0.5},
        ]
        self.assertEqual(pick_default_winner(sides), "m4b")

    def test_smaller_size_wins_same_format(self) -> None:
        small = summarize_files([{"name": "book.mp3", "size_bytes": 100}])
        large = summarize_files([{"name": "book.mp3", "size_bytes": 900}])
        sides = [
            {"side_id": "large", "file_count": large["file_count"], "total_size_bytes": large["total_size_bytes"],
             "dominant_format": large["dominant_format"], "confidence": 0.9},
            {"side_id": "small", "file_count": small["file_count"], "total_size_bytes": small["total_size_bytes"],
             "dominant_format": small["dominant_format"], "confidence": 0.5},
        ]
        self.assertEqual(pick_default_winner(sides), "small")

    def test_seed_vs_occupied_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library_root = root / "lib"
            source_root = root / "src"
            target_key = compute_target_key("Author", "Title")
            author_dir, title_dir = target_key.split("/", 1)
            target_dir = library_root / author_dir / title_dir
            target_dir.mkdir(parents=True)
            (target_dir / "existing.mp3").write_bytes(b"x" * 100)

            seed_path = source_root / "seed" / "book.m4b"
            seed_path.parent.mkdir(parents=True)
            seed_path.write_bytes(b"y" * 50)

            rows = [
                _seed_row(
                    "seed1",
                    "Author",
                    "Title",
                    source_path="seed",
                    file_source="seed/book.m4b",
                    file_name="book.m4b",
                    size_bytes=50,
                )
            ]
            lib_index = build_library_index(library_root)
            inode_index = build_inode_index(library_root)
            groups, conflict_ids = detect_conflict_groups(
                rows, library_root, source_root, {}, lib_index, inode_index
            )
            self.assertEqual(conflict_ids, {"seed1"})
            self.assertEqual(len(groups), 1)
            self.assertTrue(groups[0]["has_library_side"])
            self.assertEqual(groups[0]["conflict_kind"], "staged")
            self.assertEqual(groups[0]["winner_side_id"], LIBRARY_SIDE_ID)
            self.assertEqual(groups[0]["computed_winner_side_id"], LIBRARY_SIDE_ID)
            lib_side = next(s for s in groups[0]["sides"] if s["type"] == "library")
            self.assertEqual(lib_side["confidence"], 1.0)
            side_types = {s["type"] for s in groups[0]["sides"]}
            self.assertEqual(side_types, {"seed", "library"})

    def test_mixed_conflict_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library_root = root / "lib"
            source_root = root / "src"
            target_key = compute_target_key("Author", "Title")
            author_dir, title_dir = target_key.split("/", 1)
            target_dir = library_root / author_dir / title_dir
            target_dir.mkdir(parents=True)
            (target_dir / "existing.mp3").write_bytes(b"x" * 100)

            for seed_id, rel in (("a", "seed/a/book.m4b"), ("b", "seed/b/book.mp3")):
                path = source_root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"y" * 50)

            rows = [
                _seed_row(
                    "a",
                    "Author",
                    "Title",
                    source_path="seed/a",
                    file_source="seed/a/book.m4b",
                    file_name="book.m4b",
                    size_bytes=50,
                ),
                _seed_row(
                    "b",
                    "Author",
                    "Title",
                    source_path="seed/b",
                    file_source="seed/b/book.mp3",
                    file_name="book.mp3",
                    size_bytes=50,
                ),
            ]
            lib_index = build_library_index(library_root)
            inode_index = build_inode_index(library_root)
            groups, conflict_ids = detect_conflict_groups(
                rows, library_root, source_root, {}, lib_index, inode_index
            )
            self.assertEqual(len(groups), 1)
            self.assertEqual(conflict_ids, {"a", "b"})
            self.assertEqual(groups[0]["conflict_kind"], "mixed")
            self.assertEqual(groups[0]["winner_side_id"], LIBRARY_SIDE_ID)

    def test_persisted_winner_preselected(self) -> None:
        rows = [
            _seed_row("a", "Author", "Title", source_path="a", file_source="a/a.mp3", file_name="a.mp3", size_bytes=1000),
            _seed_row("b", "Author", "Title", source_path="b", file_source="b/b.m4b", file_name="b.m4b", size_bytes=500),
        ]
        key = compute_target_key("Author", "Title")
        groups, _ = detect_conflict_groups(rows, Path("/lib"), Path("/src"), {key: "a"}, {}, {})
        self.assertEqual(groups[0]["winner_side_id"], "a")
        self.assertEqual(groups[0]["persisted_winner_side_id"], "a")

    def test_library_side_id_constant(self) -> None:
        self.assertEqual(LIBRARY_SIDE_ID, "library")

    def test_book_target_key_uses_effective(self) -> None:
        row = {
            "chosen_author": "A",
            "chosen_title": "T",
            "chosen_author_set": 1,
            "chosen_title_set": 1,
            "chosen_series": "Series",
            "chosen_series_index": "1",
            "chosen_series_set": 1,
            "chosen_series_index_set": 1,
            "suggested_author": "X",
            "suggested_title": "Y",
            "suggested_series": "",
            "suggested_series_state": "unknown",
            "flatten_name": "flat",
        }
        key = book_target_key(row)
        self.assertEqual(key, compute_target_key("A", "T", "Series", "1"))

    def test_library_index_three_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lib"
            audio = root / "Author" / "Series" / "1 - Title" / "book.m4b"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"x")
            index = build_library_index(root)
            self.assertIn("Author/Series/1 - Title", index)

    def test_resolve_winner_metadata_uses_overrides(self) -> None:
        author, title, series, series_index = resolve_winner_metadata(
            chosen_author="Old Author",
            chosen_title="Old Title",
            suggested_author="S Author",
            suggested_title="S Title",
            flatten_name="flat",
            override_author="New Author",
            override_title="New Title",
        )
        self.assertEqual(author, "New Author")
        self.assertEqual(title, "New Title")

    def test_resolve_winner_metadata_falls_back_without_overrides(self) -> None:
        author, title, _series, _index = resolve_winner_metadata(
            chosen_author="",
            chosen_title="",
            suggested_author="S Author",
            suggested_title="S Title",
            flatten_name="flat",
        )
        self.assertEqual(author, "S Author")
        self.assertEqual(title, "S Title")


if __name__ == "__main__":
    unittest.main()
