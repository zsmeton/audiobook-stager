from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.discovery import (
    discover_books,
    files_are_single_book,
    looks_like_part,
    stem_base,
)


def _touch_mp3(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class PartDetectionTests(unittest.TestCase):
    def test_p_suffix_looks_like_part_and_stem_base(self) -> None:
        names = [f"MISTBORN0101P{i:02d}.mp3" for i in range(1, 7)]
        for name in names:
            self.assertTrue(looks_like_part(name), name)
            self.assertEqual(stem_base(Path(name).stem), "MISTBORN0101", name)
        self.assertTrue(files_are_single_book(names))

    def test_trailing_part_without_separator(self) -> None:
        for name in ("KingofThornsUnabridgedPart1.mp3", "KingofThornsUnabridgedPart2.mp3"):
            self.assertTrue(looks_like_part(name), name)
            self.assertEqual(stem_base(Path(name).stem), "KingofThornsUnabridged", name)
        self.assertTrue(
            files_are_single_book(
                ["KingofThornsUnabridgedPart1.mp3", "KingofThornsUnabridgedPart2.mp3"]
            )
        )

    def test_numbered_prefix_with_p_suffix_regression(self) -> None:
        names = [f"{i:03d}_MISTBORN0701P{i:02d}.mp3" for i in range(1, 4)]
        for name in names:
            self.assertTrue(looks_like_part(name), name)
        self.assertTrue(files_are_single_book(names))


class DiscoverBooksPartGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_king_of_thorns_parts_discover_as_single_book(self) -> None:
        book_dir = self.root / "King of Thorns"
        _touch_mp3(book_dir / "KingofThornsUnabridgedPart1.mp3")
        _touch_mp3(book_dir / "KingofThornsUnabridgedPart2.mp3")

        books = discover_books(self.root)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0].grouping, "folder")
        self.assertEqual(len(books[0].files), 2)

    def test_mistborn_p_suffix_discover_as_single_book(self) -> None:
        book_dir = self.root / "Mistborn"
        for i in range(1, 7):
            _touch_mp3(book_dir / f"MISTBORN0101P{i:02d}.mp3")

        books = discover_books(self.root)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0].grouping, "folder")
        self.assertEqual(len(books[0].files), 6)

    def test_numbered_prefix_p_suffix_discover_as_single_book(self) -> None:
        book_dir = self.root / "Mistborn 7"
        for i in range(1, 4):
            _touch_mp3(book_dir / f"{i:03d}_MISTBORN0701P{i:02d}.mp3")

        books = discover_books(self.root)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0].grouping, "folder")
        self.assertEqual(len(books[0].files), 3)
