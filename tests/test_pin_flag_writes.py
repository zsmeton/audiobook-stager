from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app.main
from app.api import (
    ConflictApprove,
    ConflictSaveEditsBody,
    ConflictSeedEdit,
    MergeApprove,
    approve_book,
    approve_conflict,
    approve_merge,
    holder,
    save_conflict_edits,
)
from app.db import _utcnow, connect
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.staging import compute_target_key, replace_library_target

_FLAG_COLUMNS = (
    "chosen_author_set",
    "chosen_title_set",
    "chosen_series_set",
    "chosen_series_index_set",
)


def _insert_book(
    conn,
    book_id: str,
    author: str,
    title: str,
    *,
    file_source: str,
    file_name: str,
    size_bytes: int,
    series: str = "",
    series_index: str = "",
) -> None:
    files = [{"name": file_name, "source": file_source, "size_bytes": size_bytes}]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, suggested_series, suggested_series_index,
            suggested_series_state,
            chosen_author, chosen_title, chosen_series, chosen_series_index,
            chosen_author_set, chosen_title_set, chosen_series_set, chosen_series_index_set,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending',
            ?, ?, ?, ?, 'confirmed',
            ?, ?, ?, ?,
            0, 0, 0, 0,
            0.5, '', '{}', '[]', 'ok', ?
        )
        """,
        (
            book_id,
            file_source.rsplit("/", 1)[0],
            json.dumps(file_source.split("/")),
            "",
            "",
            "flat",
            title,
            "",
            json.dumps(files),
            author,
            title,
            series,
            series_index,
            author,
            title,
            series,
            series_index,
            _utcnow(),
        ),
    )
    conn.commit()


def _flag_row(conn, book_id: str):
    return conn.execute(
        """
        SELECT chosen_author, chosen_title, chosen_series, chosen_series_index,
               chosen_author_set, chosen_title_set,
               chosen_series_set, chosen_series_index_set
        FROM books WHERE id = ?
        """,
        (book_id,),
    ).fetchone()


def _assert_flags(test: unittest.TestCase, row, expected: int) -> None:
    for column in _FLAG_COLUMNS:
        test.assertEqual(int(row[column] or 0), expected, column)


def _assert_flag_map(test: unittest.TestCase, row, expected: dict[str, int]) -> None:
    for column, value in expected.items():
        test.assertEqual(int(row[column] or 0), value, column)


class _HolderFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.library_root = self.root / "lib"
        self.books_root.mkdir()
        self.library_root.mkdir()
        self.conn = connect(self.root / "test.db")
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
        holder.auto_manager = None
        self.conn.close()
        self.tmp.cleanup()

    def _write_seed(self, rel: str, payload: bytes) -> None:
        path = self.books_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


class NormalApprovePinFlagTests(_HolderFixture):
    def test_approve_copies_effective_values_without_setting_pin_flags(self) -> None:
        rel = "Ada/The Book/book.m4b"
        self._write_seed(rel, b"audio")
        _insert_book(
            self.conn,
            "book1",
            "Ada",
            "The Book",
            file_source=rel,
            file_name="book.m4b",
            size_bytes=5,
            series="The Series",
            series_index="2",
        )

        approve_book("book1")

        row = _flag_row(self.conn, "book1")
        self.assertEqual(row["chosen_author"], "Ada")
        self.assertEqual(row["chosen_title"], "The Book")
        self.assertEqual(row["chosen_series"], "The Series")
        self.assertEqual(row["chosen_series_index"], "2")
        _assert_flags(self, row, 0)
        staged = self.conn.execute(
            "SELECT status, staged_path FROM books WHERE id = 'book1'"
        ).fetchone()
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(
            staged["staged_path"],
            compute_target_key("Ada", "The Book", "The Series", "2"),
        )


class ConflictPinFlagTests(_HolderFixture):
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

    def test_save_edits_pins_each_supplied_nonempty_field(self) -> None:
        result = save_conflict_edits(
            self.target_key,
            ConflictSaveEditsBody(
                edits=[
                    ConflictSeedEdit(
                        book_id="seed1",
                        chosen_author="Edited Author",
                        chosen_title="Edited Title",
                        chosen_series="Edited Series",
                        chosen_series_index="4",
                    )
                ]
            ),
        )

        self.assertEqual(result["saved"], 1)
        row = _flag_row(self.conn, "seed1")
        self.assertEqual(row["chosen_author"], "Edited Author")
        self.assertEqual(row["chosen_title"], "Edited Title")
        self.assertEqual(row["chosen_series"], "Edited Series")
        self.assertEqual(row["chosen_series_index"], "4")
        _assert_flag_map(
            self,
            row,
            {
                "chosen_author_set": 1,
                "chosen_title_set": 1,
                "chosen_series_set": 1,
                "chosen_series_index_set": 1,
            },
        )

    def test_approve_with_override_pins_only_the_supplied_field(self) -> None:
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
        self.assertEqual(row["chosen_series"], "")
        self.assertEqual(row["chosen_series_index"], "")
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

    def test_approve_without_override_leaves_pin_flags_unset(self) -> None:
        approve_conflict(
            self.target_key,
            ConflictApprove(winner_side="seed1"),
        )

        row = _flag_row(self.conn, "seed1")
        self.assertEqual(row["chosen_author"], "Author")
        self.assertEqual(row["chosen_title"], "Title")
        _assert_flags(self, row, 0)


class MergeApprovePinFlagTests(_HolderFixture):
    def setUp(self) -> None:
        super().setUp()
        self.target_key = compute_target_key("Author", "Title")
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
            )
        holder.session.rebuild_target_indexes()

    def test_approve_with_override_pins_only_the_supplied_field_on_primary(self) -> None:
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
        self.assertEqual(primary["chosen_series"], "")
        self.assertEqual(primary["chosen_series_index"], "")
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
        _assert_flags(self, _flag_row(self.conn, "part2"), 0)

    def test_approve_without_override_leaves_pin_flags_unset(self) -> None:
        approve_merge(
            self.target_key,
            MergeApprove(
                primary_book_id="part1",
                member_book_ids=["part1", "part2"],
            ),
        )

        primary = _flag_row(self.conn, "part1")
        self.assertEqual(primary["chosen_author"], "Author")
        self.assertEqual(primary["chosen_title"], "Title")
        _assert_flags(self, primary, 0)
        _assert_flags(self, _flag_row(self.conn, "part2"), 0)


class SeriesLibraryReplaceTests(unittest.TestCase):
    def test_replace_with_series_deletes_series_directory_and_leaves_flat(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        library = Path(tmp.name) / "library"
        library.mkdir()
        flat = library / "Author" / "Title"
        flat.mkdir(parents=True)
        (flat / "flat.mp3").write_bytes(b"flat")
        series_key = compute_target_key("Author", "Title", "The Series", "2")
        series_dir = library.joinpath(*series_key.split("/"))
        series_dir.mkdir(parents=True)
        series_file = series_dir / "book.mp3"
        series_file.write_bytes(b"series")

        result = replace_library_target(library, "Author", "Title", "The Series", "2")

        self.assertEqual(result.status, "replaced")
        self.assertEqual(result.target_path, series_key)
        self.assertEqual(result.files_linked, 1)
        self.assertFalse(series_file.exists())
        self.assertTrue((flat / "flat.mp3").is_file())
