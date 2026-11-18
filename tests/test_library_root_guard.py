from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.discovery import AudioFile, FlatBook
from stager_core.staging import (
    _assert_target_under_library,
    remove_extra_library_files,
    replace_library_target,
)


def _book() -> FlatBook:
    return FlatBook(
        id="book1",
        flatten_name="Title",
        source_path="seed",
        source_path_parts=["seed"],
        top_level_pack="",
        parent_context="",
        grouping="flat",
        files=[AudioFile(name="book.mp3", source="book.mp3", size_bytes=4)],
        flatten_target="",
    )


class LibraryRootGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_guard_accepts_path_below_library_and_refuses_root_or_outside(self) -> None:
        _assert_target_under_library(self.library, self.library / "Author" / "Title")

        with self.assertRaises(ValueError) as at_root:
            _assert_target_under_library(self.library, self.library)
        self.assertEqual(str(at_root.exception), "target path must be below library root")

        outside = self.root / "sibling"
        with self.assertRaises(ValueError) as escaped:
            _assert_target_under_library(self.library, outside)
        self.assertIn("not in the subpath", str(escaped.exception))

    def test_remove_extras_refuses_library_root_and_leaves_the_file(self) -> None:
        books = self.root / "books"
        books.mkdir()
        (books / "book.mp3").write_bytes(b"seed")
        extra = self.library / "extra.mp3"
        extra.write_bytes(b"extra")

        result = remove_extra_library_files(
            books,
            self.library,
            _book(),
            ".",
            {},
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "target path must be below library root")
        self.assertTrue(extra.is_file())

    def test_replace_collapses_parent_segments_and_stays_inside_library(self) -> None:
        result = replace_library_target(self.library, "..", "..")

        self.assertEqual(result.status, "replaced")
        self.assertEqual(result.target_path, "untitled/untitled")
        self.assertEqual(list(self.library.iterdir()), [])
        self.assertFalse((self.root / "untitled").exists())
        _assert_target_under_library(self.library, self.library / "untitled" / "untitled")
