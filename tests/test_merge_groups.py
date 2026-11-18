from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.api import (
    ConflictApprove,
    MergeApprove,
    approve_conflict,
    approve_conflict_merge,
    approve_merge,
    get_conflict,
    holder,
    preview_merge,
)
from app.db import _utcnow, connect
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.conflicts import build_library_index, detect_conflict_groups
from stager_core.discovery import AudioFile, FlatBook
from stager_core.merges import detect_merge_groups
from stager_core.staging import (
    build_inode_index,
    compute_target_key,
    resolve_merged_staged_names,
    stage_merged_books,
)


def _insert_seed(
    conn,
    book_id: str,
    author: str,
    title: str,
    *,
    file_source: str,
    file_name: str,
    size_bytes: int,
) -> None:
    files = [{"name": file_name, "source": file_source, "size_bytes": size_bytes}]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0.5, '', '{}', '[]', 'ok', ?)
        """,
        (
            book_id,
            file_source.rsplit("/", 1)[0],
            json.dumps(file_source.split("/")),
            None,
            None,
            "flat",
            title,
            "",
            json.dumps(files),
            author,
            title,
            author,
            title,
            _utcnow(),
        ),
    )
    conn.commit()


def _seed_row(
    book_id: str,
    author: str,
    title: str,
    *,
    source_path: str,
    file_source: str,
    file_name: str,
    size_bytes: int,
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
        "confidence": 0.5,
        "files": [{"name": file_name, "source": file_source, "size_bytes": size_bytes}],
        "tags": {},
        "candidates": [],
    }


class DetectMergeGroupsTests(unittest.TestCase):
    def test_two_pending_same_key_creates_group(self) -> None:
        rows = [
            _seed_row(
                "a",
                "Author",
                "Title",
                source_path="seed/a",
                file_source="seed/a/part1.m4b",
                file_name="part1.m4b",
                size_bytes=50,
            ),
            _seed_row(
                "b",
                "Author",
                "Title",
                source_path="seed/b",
                file_source="seed/b/part2.m4b",
                file_name="part2.m4b",
                size_bytes=60,
            ),
        ]
        groups, merge_ids = detect_merge_groups(
            rows, Path("/nonexistent/lib"), Path("/nonexistent/src"), {}, {}
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(merge_ids, {"a", "b"})
        self.assertEqual(groups[0]["member_book_ids"], ["a", "b"])

    def test_library_side_excludes_merge_group(self) -> None:
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
            seed_path.parent.mkdir(parents=True, exist_ok=True)
            seed_path.write_bytes(b"y" * 50)

            rows = [
                _seed_row(
                    "a",
                    "Author",
                    "Title",
                    source_path="seed/a",
                    file_source="seed/a/part1.m4b",
                    file_name="part1.m4b",
                    size_bytes=50,
                ),
                _seed_row(
                    "b",
                    "Author",
                    "Title",
                    source_path="seed/b",
                    file_source="seed/b/part2.m4b",
                    file_name="part2.m4b",
                    size_bytes=60,
                ),
            ]
            lib_index = build_library_index(library_root)
            inode_index = build_inode_index(library_root)
            groups, merge_ids = detect_merge_groups(
                rows, library_root, source_root, lib_index, inode_index
            )
            self.assertEqual(groups, [])
            self.assertEqual(merge_ids, set())


class MergeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.library_root = self.root / "lib"
        self.books_root.mkdir()
        self.library_root.mkdir()

        self.target_key = compute_target_key("Author", "Title")
        for book_id, rel, name in (
            ("part1", "seed/part1/part1.m4b", "part1.m4b"),
            ("part2", "seed/part2/part2.m4b", "part2.m4b"),
        ):
            path = self.books_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 40)

        self.conn = connect(self.root / "test.db")
        for book_id, rel, name in (
            ("part1", "seed/part1/part1.m4b", "part1.m4b"),
            ("part2", "seed/part2/part2.m4b", "part2.m4b"),
        ):
            _insert_seed(
                self.conn,
                book_id,
                "Author",
                "Title",
                file_source=rel,
                file_name=name,
                size_bytes=40,
            )

        holder.conn = self.conn
        holder.session = StagingSession(self.books_root, self.library_root)
        holder.session.rebuild_target_indexes()
        holder.manager = ScanManager(
            self.conn, self.books_root, self.library_root, holder.session
        )

    def tearDown(self) -> None:
        holder.session = None
        holder.conn = None
        holder.manager = None
        self.conn.close()
        self.tmp.cleanup()

    def test_merge_clears_conflict_group(self) -> None:
        conflicts_before, _ = detect_conflict_groups(
            [
                {
                    "id": "part1",
                    "status": "pending",
                    "chosen_author": "Author",
                    "chosen_title": "Title",
                    "suggested_author": "",
                    "suggested_title": "",
                    "flatten_name": "Title",
                    "source_path": "seed/part1",
                    "confidence": 0.5,
                    "files": [{"name": "part1.m4b", "source": "seed/part1/part1.m4b", "size_bytes": 40}],
                    "tags": {},
                    "candidates": [],
                },
                {
                    "id": "part2",
                    "status": "pending",
                    "chosen_author": "Author",
                    "chosen_title": "Title",
                    "suggested_author": "",
                    "suggested_title": "",
                    "flatten_name": "Title",
                    "source_path": "seed/part2",
                    "confidence": 0.5,
                    "files": [{"name": "part2.m4b", "source": "seed/part2/part2.m4b", "size_bytes": 40}],
                    "tags": {},
                    "candidates": [],
                },
            ],
            self.library_root,
            self.books_root,
            {},
            holder.session.library_index,
            holder.session.inode_index,
        )
        self.assertEqual(len(conflicts_before), 1)

        result = approve_merge(
            self.target_key,
            MergeApprove(primary_book_id="part1", member_book_ids=["part1", "part2"]),
        )
        self.assertEqual(result["status"], "merged")
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["merges"], [])

        primary = self.conn.execute(
            "SELECT status, staged_path FROM books WHERE id = 'part1'"
        ).fetchone()
        member = self.conn.execute(
            "SELECT status, merged_into FROM books WHERE id = 'part2'"
        ).fetchone()
        self.assertEqual(primary["status"], "staged")
        self.assertEqual(member["status"], "merged")
        self.assertEqual(member["merged_into"], "part1")

        author_dir, title_dir = self.target_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        self.assertTrue((target_dir / "part1.m4b").is_file())
        self.assertTrue((target_dir / "part2.m4b").is_file())

    def test_conflict_approve_clears_merge_group(self) -> None:
        result = approve_conflict(
            self.target_key,
            ConflictApprove(winner_side="part1"),
        )
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["merges"], [])

        member = self.conn.execute(
            "SELECT status FROM books WHERE id = 'part2'"
        ).fetchone()
        self.assertEqual(member["status"], "skipped")

    def test_partial_merge_leaves_unselected_pending(self) -> None:
        part3_path = self.books_root / "seed/part3/part3.m4b"
        part3_path.parent.mkdir(parents=True, exist_ok=True)
        part3_path.write_bytes(b"x" * 40)
        _insert_seed(
            self.conn,
            "part3",
            "Author",
            "Title",
            file_source="seed/part3/part3.m4b",
            file_name="part3.m4b",
            size_bytes=40,
        )
        holder.session.refresh_resolution_groups(self.conn)

        result = approve_merge(
            self.target_key,
            MergeApprove(primary_book_id="part1", member_book_ids=["part1", "part2"]),
        )
        self.assertEqual(result["status"], "merged")
        self.assertEqual(len(result["merges"]), 0)

        part3 = self.conn.execute(
            "SELECT status, merged_into FROM books WHERE id = 'part3'"
        ).fetchone()
        part2 = self.conn.execute(
            "SELECT status, merged_into FROM books WHERE id = 'part2'"
        ).fetchone()
        part1 = self.conn.execute(
            "SELECT status FROM books WHERE id = 'part1'"
        ).fetchone()
        self.assertEqual(part1["status"], "staged")
        self.assertEqual(part2["status"], "merged")
        self.assertEqual(part2["merged_into"], "part1")
        self.assertEqual(part3["status"], "pending")
        self.assertEqual(part3["merged_into"], "")

    def test_preview_merge_includes_staged_files(self) -> None:
        preview = preview_merge(self.target_key, None)
        self.assertIn("staged_files", preview)
        self.assertIn("filename_conflicts", preview)
        self.assertEqual(len(preview["staged_files"]), 2)
        self.assertEqual(preview["filename_conflicts"], [])
        staged_names = {entry["staged_name"] for entry in preview["staged_files"]}
        self.assertEqual(staged_names, {"part1.m4b", "part2.m4b"})

    def test_preview_merge_reports_duplicate_basenames(self) -> None:
        shared_name = "part.m4b"
        for book_id, rel in (("part1", "seed/part1/part1.m4b"), ("part2", "seed/part2/part2.m4b")):
            self.conn.execute(
                "UPDATE books SET files_json = ? WHERE id = ?",
                (
                    json.dumps(
                        [{"name": shared_name, "source": rel, "size_bytes": 40}]
                    ),
                    book_id,
                ),
            )
        self.conn.commit()
        holder.session.refresh_resolution_groups(self.conn)

        preview = preview_merge(self.target_key, None)
        conflict = next(
            item for item in preview["filename_conflicts"] if item["basename"] == shared_name
        )
        self.assertEqual(conflict["count"], 2)
        prefixed = [
            entry for entry in preview["staged_files"] if entry["basename"] == shared_name
        ]
        self.assertEqual(len(prefixed), 2)
        self.assertNotEqual(prefixed[0]["staged_name"], prefixed[1]["staged_name"])

    def test_merge_without_primary_picks_highest_confidence(self) -> None:
        self.conn.execute(
            "UPDATE books SET confidence = 0.9 WHERE id = 'part2'"
        )
        self.conn.execute(
            "UPDATE books SET confidence = 0.2 WHERE id = 'part1'"
        )
        self.conn.commit()
        holder.session.refresh_resolution_groups(self.conn)

        result = approve_merge(
            self.target_key,
            MergeApprove(member_book_ids=["part1", "part2"]),
        )
        self.assertEqual(result["primary_book_id"], "part2")

    def test_conflict_get_includes_merge_eligible_seed_ids(self) -> None:
        group = get_conflict(self.target_key)
        self.assertEqual(group["merge_eligible_seed_ids"], ["part1", "part2"])

    def test_conflict_merge_stages_selected_seeds(self) -> None:
        result = approve_conflict_merge(
            self.target_key,
            MergeApprove(member_book_ids=["part1", "part2"]),
        )
        self.assertEqual(result["status"], "merged")
        self.assertEqual(result["conflicts"], [])

        primary = self.conn.execute(
            "SELECT status, staged_path FROM books WHERE id = ?",
            (result["primary_book_id"],),
        ).fetchone()
        self.assertEqual(primary["status"], "staged")

        author_dir, title_dir = self.target_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        self.assertTrue((target_dir / "part1.m4b").is_file())
        self.assertTrue((target_dir / "part2.m4b").is_file())

    def test_merge_with_staged_names_override(self) -> None:
        overrides = {
            "seed/part1/part1.m4b": "disc1_opening.m4b",
            "seed/part2/part2.m4b": "disc2_closing.m4b",
        }
        result = approve_merge(
            self.target_key,
            MergeApprove(
                primary_book_id="part1",
                member_book_ids=["part1", "part2"],
                staged_names=overrides,
            ),
        )
        self.assertEqual(result["status"], "merged")

        author_dir, title_dir = self.target_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        self.assertTrue((target_dir / "disc1_opening.m4b").is_file())
        self.assertTrue((target_dir / "disc2_closing.m4b").is_file())
        self.assertFalse((target_dir / "part1.m4b").exists())
        self.assertFalse((target_dir / "part2.m4b").exists())

    def test_conflict_merge_with_staged_names_override(self) -> None:
        overrides = {
            "seed/part1/part1.m4b": "merged_a.m4b",
            "seed/part2/part2.m4b": "merged_b.m4b",
        }
        result = approve_conflict_merge(
            self.target_key,
            MergeApprove(
                member_book_ids=["part1", "part2"],
                staged_names=overrides,
            ),
        )
        self.assertEqual(result["status"], "merged")

        author_dir, title_dir = self.target_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        self.assertTrue((target_dir / "merged_a.m4b").is_file())
        self.assertTrue((target_dir / "merged_b.m4b").is_file())


class ResolveMergedStagedNamesTests(unittest.TestCase):
    def test_duplicate_basenames_get_distinct_staged_names(self) -> None:
        primary = FlatBook(
            id="a",
            flatten_name="Part A",
            source_path="seed/a",
            source_path_parts=["seed", "a"],
            top_level_pack="",
            parent_context="",
            grouping="flat",
            files=[AudioFile(name="track.m4b", source="seed/a/track.m4b", size_bytes=10)],
        )
        member = FlatBook(
            id="b",
            flatten_name="Part B",
            source_path="seed/b",
            source_path_parts=["seed", "b"],
            top_level_pack="",
            parent_context="",
            grouping="flat",
            files=[AudioFile(name="track.m4b", source="seed/b/track.m4b", size_bytes=10)],
        )
        staged_files, filename_conflicts = resolve_merged_staged_names(primary, [member])
        self.assertEqual(filename_conflicts, [{"basename": "track.m4b", "count": 2}])
        self.assertEqual(staged_files[0]["staged_name"], "track.m4b")
        self.assertEqual(staged_files[1]["staged_name"], "Part B_track.m4b")

    def test_staged_name_overrides_honored(self) -> None:
        primary = FlatBook(
            id="a",
            flatten_name="Part A",
            source_path="seed/a",
            source_path_parts=["seed", "a"],
            top_level_pack="",
            parent_context="",
            grouping="flat",
            files=[AudioFile(name="track.m4b", source="seed/a/track.m4b", size_bytes=10)],
        )
        member = FlatBook(
            id="b",
            flatten_name="Part B",
            source_path="seed/b",
            source_path_parts=["seed", "b"],
            top_level_pack="",
            parent_context="",
            grouping="flat",
            files=[AudioFile(name="track.m4b", source="seed/b/track.m4b", size_bytes=10)],
        )
        overrides = {
            "seed/a/track.m4b": "custom_a.m4b",
            "seed/b/track.m4b": "custom_b.m4b",
        }
        staged_files, filename_conflicts = resolve_merged_staged_names(
            primary, [member], staged_name_overrides=overrides
        )
        self.assertEqual(filename_conflicts, [{"basename": "track.m4b", "count": 2}])
        self.assertEqual(staged_files[0]["staged_name"], "custom_a.m4b")
        self.assertEqual(staged_files[1]["staged_name"], "custom_b.m4b")


class StageMergedBooksOverrideTests(unittest.TestCase):
    def test_stage_merged_books_rejects_duplicate_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "src"
            library_root = root / "lib"
            library_root.mkdir()
            for rel in ("seed/a/track.m4b", "seed/b/track.m4b"):
                path = source_root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * 10)

            primary = FlatBook(
                id="a",
                flatten_name="A",
                source_path="seed/a",
                source_path_parts=["seed", "a"],
                top_level_pack="",
                parent_context="",
                grouping="flat",
                files=[AudioFile(name="track.m4b", source="seed/a/track.m4b", size_bytes=10)],
            )
            member = FlatBook(
                id="b",
                flatten_name="B",
                source_path="seed/b",
                source_path_parts=["seed", "b"],
                top_level_pack="",
                parent_context="",
                grouping="flat",
                files=[AudioFile(name="track.m4b", source="seed/b/track.m4b", size_bytes=10)],
            )
            result = stage_merged_books(
                source_root,
                library_root,
                primary,
                [member],
                "Author",
                "Title",
                {},
                staged_name_overrides={
                    "seed/a/track.m4b": "same.m4b",
                    "seed/b/track.m4b": "same.m4b",
                },
            )
            self.assertEqual(result.status, "name_collision")


if __name__ == "__main__":
    unittest.main()
