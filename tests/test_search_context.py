from __future__ import annotations

import unittest

from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.query import build_search_context
from stager_core.metadata.types import ManualHints, TagInfo


def _book() -> FlatBook:
    return FlatBook(
        id="book1",
        flatten_name="Folder Title",
        source_path="Author Name/Folder Title",
        source_path_parts=["Author Name", "Folder Title"],
        top_level_pack="Author Name",
        parent_context="",
        grouping="folder",
        files=[AudioFile(name="file.m4b", source="Author Name/Folder Title/file.m4b", size_bytes=1)],
        flatten_target="Folder Title",
    )


def _tags(**kwargs: str) -> TagInfo:
    return TagInfo(
        title=kwargs.get("title", "Tag Title"),
        album=kwargs.get("album", "Tag Album"),
        artist=kwargs.get("artist", "Tag Artist"),
        albumartist=kwargs.get("albumartist", "Tag Album Artist"),
    )


class BuildSearchContextTests(unittest.TestCase):
    def test_empty_manual_uses_tags_and_path(self) -> None:
        ctx = build_search_context(_book(), _tags())
        self.assertEqual(ctx["title"], "Tag Title")
        self.assertEqual(ctx["author"], "Tag Artist")
        self.assertFalse(ctx["manual_used"])

    def test_manual_title_only(self) -> None:
        ctx = build_search_context(
            _book(),
            _tags(),
            ManualHints(title="Manual Title"),
        )
        self.assertEqual(ctx["title"], "Manual Title")
        self.assertEqual(ctx["author"], "Tag Artist")
        self.assertTrue(ctx["manual_used"])

    def test_manual_author_only(self) -> None:
        ctx = build_search_context(
            _book(),
            _tags(),
            ManualHints(author="Manual Author"),
        )
        self.assertEqual(ctx["title"], "Tag Title")
        self.assertEqual(ctx["author"], "Manual Author")
        self.assertTrue(ctx["manual_used"])

    def test_manual_title_and_author(self) -> None:
        ctx = build_search_context(
            _book(),
            _tags(),
            ManualHints(author="Manual Author", title="Manual Title"),
        )
        self.assertEqual(ctx["title"], "Manual Title")
        self.assertEqual(ctx["author"], "Manual Author")
        self.assertTrue(ctx["manual_used"])

    def test_blank_manual_fields_fall_through(self) -> None:
        ctx = build_search_context(
            _book(),
            _tags(),
            ManualHints(author="  ", title=""),
        )
        self.assertEqual(ctx["title"], "Tag Title")
        self.assertEqual(ctx["author"], "Tag Artist")
        self.assertFalse(ctx["manual_used"])

    def _empire_of_storms_book(self) -> FlatBook:
        return FlatBook(
            id="book1",
            flatten_name="Throne of Glass 5 - Empire of Storms",
            source_path="Throne of Glass - Complete Chronological Collection/Audiobooks/Throne of Glass 5 - Empire of Storms",
            source_path_parts=[
                "Throne of Glass - Complete Chronological Collection",
                "Audiobooks",
                "Throne of Glass 5 - Empire of Storms",
            ],
            top_level_pack="Throne of Glass - Complete Chronological Collection",
            parent_context="Audiobooks",
            grouping="folder",
            files=[
                AudioFile(
                    name="01 - Nightfall.mp3",
                    source="Throne of Glass - Complete Chronological Collection/Audiobooks/Throne of Glass 5 - Empire of Storms/01 - Nightfall.mp3",
                    size_bytes=1,
                )
            ],
            flatten_target="Throne of Glass 5 - Empire of Storms",
        )

    def _empire_of_storms_tags(self) -> TagInfo:
        return TagInfo(
            title="Nightfall",
            album="Empire of Storms, Throne of Glass, Book 5",
            artist="Sarah J. Maas (Elizabeth Evans)",
            albumartist="Sarah J. Maas (Elizabeth Evans)",
        )

    def test_manual_hints_ignore_misleading_tags_and_filenames(self) -> None:
        ctx = build_search_context(
            self._empire_of_storms_book(),
            self._empire_of_storms_tags(),
            ManualHints(author="Sarah J. Maas", title="Empire of Storms"),
        )
        self.assertEqual(ctx["title"], "Empire of Storms")
        self.assertEqual(ctx["author"], "Sarah J. Maas")
        self.assertTrue(ctx["manual_used"])

    def test_manual_author_only_title_falls_back_to_tags(self) -> None:
        ctx = build_search_context(
            self._empire_of_storms_book(),
            self._empire_of_storms_tags(),
            ManualHints(author="Sarah J. Maas"),
        )
        self.assertEqual(ctx["author"], "Sarah J. Maas")
        self.assertEqual(ctx["title"], "Nightfall")
        self.assertTrue(ctx["manual_used"])


if __name__ == "__main__":
    unittest.main()
