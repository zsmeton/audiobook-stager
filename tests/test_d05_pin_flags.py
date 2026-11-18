"""Pin flags for conflict save-edits, conflict approve, and merge approve.

D05: those writes follow a normal field edit. They may copy effective values into
chosen_*, and they set chosen_*_set only when the operator pinned that field
the way a normal field edit does (the field is present, and empty series or
series index stays unpinned when there is no suggestion and no existing pin).
"""

from __future__ import annotations

import unittest

import app.main
from app.api import (
    ConflictApprove,
    ConflictSaveEditsBody,
    ConflictSeedEdit,
    MergeApprove,
    approve_conflict,
    approve_merge,
    holder,
    save_conflict_edits,
)
from stager_core.staging import compute_target_key
from tests.test_pin_flag_writes import _HolderFixture, _flag_row, _insert_book


def _assert_flag_map(test: unittest.TestCase, row, expected: dict[str, int]) -> None:
    for column, value in expected.items():
        test.assertEqual(int(row[column] or 0), value, column)


class ConflictSaveEditsPinTests(_HolderFixture):
    def setUp(self) -> None:
        super().setUp()
        self.target_key = compute_target_key("Author", "Title")
        author_dir, title_dir = self.target_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        target_dir.mkdir(parents=True)
        (target_dir / "existing.mp3").write_bytes(b"x" * 20)
        rel = "seed/book.m4b"
        self._write_seed(rel, b"y" * 20)
        _insert_book(
            self.conn,
            "seed1",
            "Author",
            "Title",
            file_source=rel,
            file_name="book.m4b",
            size_bytes=20,
        )
        holder.session.rebuild_target_indexes()

    def test_save_edits_pins_only_fields_a_normal_edit_would_pin(self) -> None:
        result = save_conflict_edits(
            self.target_key,
            ConflictSaveEditsBody(
                edits=[
                    ConflictSeedEdit(
                        book_id="seed1",
                        chosen_author="Edited Author",
                        chosen_title="Edited Title",
                        chosen_series="",
                        chosen_series_index="",
                    )
                ]
            ),
        )

        self.assertEqual(result["saved"], 1)
        row = _flag_row(self.conn, "seed1")
        self.assertEqual(row["chosen_author"], "Edited Author")
        self.assertEqual(row["chosen_title"], "Edited Title")
        self.assertEqual(row["chosen_series"], "")
        self.assertEqual(row["chosen_series_index"], "")
        _assert_flag_map(
            self,
            row,
            {
                "chosen_author_set": 1,
                "chosen_title_set": 1,
                "chosen_series_set": 0,
                "chosen_series_index_set": 0,
            },
        )


class ConflictApprovePinTests(_HolderFixture):
    def setUp(self) -> None:
        super().setUp()
        self.target_key = compute_target_key("Author", "Title", "The Series", "2")
        target_dir = self.library_root.joinpath(*self.target_key.split("/"))
        target_dir.mkdir(parents=True)
        (target_dir / "existing.mp3").write_bytes(b"x" * 20)
        rel = "seed/book.m4b"
        self._write_seed(rel, b"y" * 20)
        _insert_book(
            self.conn,
            "seed1",
            "Author",
            "Title",
            file_source=rel,
            file_name="book.m4b",
            size_bytes=20,
            series="The Series",
            series_index="2",
        )
        holder.session.rebuild_target_indexes()

    def test_approve_pins_only_the_supplied_field(self) -> None:
        approve_conflict(
            self.target_key,
            ConflictApprove(
                winner_side="seed1",
                chosen_title="New Title",
            ),
        )

        row = _flag_row(self.conn, "seed1")
        self.assertEqual(row["chosen_author"], "Author")
        self.assertEqual(row["chosen_title"], "New Title")
        self.assertEqual(row["chosen_series"], "The Series")
        self.assertEqual(row["chosen_series_index"], "2")
        _assert_flag_map(
            self,
            row,
            {
                "chosen_author_set": 0,
                "chosen_title_set": 1,
                "chosen_series_set": 0,
                "chosen_series_index_set": 0,
            },
        )


class MergeApprovePinTests(_HolderFixture):
    def setUp(self) -> None:
        super().setUp()
        self.target_key = compute_target_key("Author", "Title", "The Series", "2")
        for book_id, rel, name in (
            ("part1", "seed/part1/part1.m4b", "part1.m4b"),
            ("part2", "seed/part2/part2.m4b", "part2.m4b"),
        ):
            self._write_seed(rel, b"x" * 40)
            _insert_book(
                self.conn,
                book_id,
                "Author",
                "Title",
                file_source=rel,
                file_name=name,
                size_bytes=40,
                series="The Series",
                series_index="2",
            )
        holder.session.rebuild_target_indexes()

    def test_approve_pins_only_the_supplied_field_on_primary(self) -> None:
        approve_merge(
            self.target_key,
            MergeApprove(
                primary_book_id="part1",
                member_book_ids=["part1", "part2"],
                chosen_title="Merged Title",
            ),
        )

        primary = _flag_row(self.conn, "part1")
        self.assertEqual(primary["chosen_author"], "Author")
        self.assertEqual(primary["chosen_title"], "Merged Title")
        self.assertEqual(primary["chosen_series"], "The Series")
        self.assertEqual(primary["chosen_series_index"], "2")
        _assert_flag_map(
            self,
            primary,
            {
                "chosen_author_set": 0,
                "chosen_title_set": 1,
                "chosen_series_set": 0,
                "chosen_series_index_set": 0,
            },
        )
        _assert_flag_map(
            self,
            _flag_row(self.conn, "part2"),
            {
                "chosen_author_set": 0,
                "chosen_title_set": 0,
                "chosen_series_set": 0,
                "chosen_series_index_set": 0,
            },
        )
