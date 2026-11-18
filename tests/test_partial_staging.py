from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from stager_core.discovery import AudioFile, FlatBook
from stager_core.staging import (
    analyze_book_staging,
    build_inode_index,
    complete_partial_stage,
    remove_extra_library_files,
    unstage_book,
)


def _multi_file_book(tmp: Path, count: int = 5) -> tuple[FlatBook, Path]:
    book_dir = tmp / "books" / "seed" / "book"
    book_dir.mkdir(parents=True)
    files: list[AudioFile] = []
    for i in range(1, count + 1):
        name = f"{i:02d}.mp3"
        rel = f"seed/book/{name}"
        path = book_dir / name
        path.write_bytes(f"audio-{i}".encode())
        files.append(AudioFile(name=name, source=rel, size_bytes=len(f"audio-{i}")))
    book = FlatBook(
        id="book1",
        flatten_name="book",
        source_path="seed/book",
        source_path_parts=["seed", "book"],
        top_level_pack="seed",
        parent_context="",
        grouping="folder",
        files=files,
        flatten_target="book",
    )
    return book, tmp / "books"


class PartialStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _link_partial(self, linked_count: int = 2, total: int = 5) -> tuple[FlatBook, Path, dict[int, list[str]], str]:
        book, source = _multi_file_book(self.root, total)
        target_dir = self.library / "Author" / "Title"
        target_dir.mkdir(parents=True)
        rel_target = "Author/Title"
        for af in book.files[:linked_count]:
            src = source / af.source.replace("/", os.sep)
            dst = target_dir / af.name
            os.link(src, dst)
        inode_index = build_inode_index(self.library)
        return book, source, inode_index, rel_target

    def test_analyze_partial_book(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(2, 5)
        analysis = analyze_book_staging(
            source,
            book,
            inode_index,
            library_root=self.library,
            author="Author",
            title="Title",
            staged_path_rel=rel_target,
        )
        self.assertEqual(analysis.detail, "partial_staged")
        self.assertEqual(analysis.linked_count, 2)
        self.assertEqual(analysis.unlinked_count, 3)
        self.assertEqual(analysis.source_missing_count, 0)
        self.assertEqual(analysis.total, 5)
        linked_files = [f for f in analysis.files if f.status == "linked"]
        unlinked_files = [f for f in analysis.files if f.status == "unlinked"]
        self.assertEqual(len(linked_files), 2)
        self.assertEqual(len(unlinked_files), 3)

    def test_analyze_detects_extra_library_files(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(2, 5)
        extra = self.library / rel_target.replace("/", os.sep) / "old_track.mp3"
        extra.write_bytes(b"orphan")
        inode_index = build_inode_index(self.library)
        analysis = analyze_book_staging(
            source,
            book,
            inode_index,
            library_root=self.library,
            staged_path_rel=rel_target,
        )
        self.assertEqual(len(analysis.extra_library_files), 1)
        self.assertEqual(analysis.extra_library_files[0].name, "old_track.mp3")

    def test_complete_partial_stage_links_remaining(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(2, 5)
        result = complete_partial_stage(
            source,
            self.library,
            book,
            "Author",
            "Title",
            inode_index,
            rel_target,
        )
        self.assertEqual(result.status, "staged")
        self.assertEqual(result.files_linked, 3)
        target_dir = self.library / "Author" / "Title"
        for af in book.files:
            dst = target_dir / af.name
            self.assertTrue(dst.is_file())
            src = source / af.source.replace("/", os.sep)
            self.assertTrue(os.path.samefile(src, dst))

    def test_complete_partial_all_linked_returns_staged(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(5, 5)
        result = complete_partial_stage(
            source,
            self.library,
            book,
            "Author",
            "Title",
            inode_index,
            rel_target,
        )
        self.assertEqual(result.status, "staged")
        self.assertEqual(result.files_skipped, 5)
        self.assertEqual(result.files_linked, 0)

    def test_complete_partial_name_collision(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(2, 5)
        target_dir = self.library / rel_target.replace("/", os.sep)
        blocker = target_dir / "03.mp3"
        blocker.write_bytes(b"different-file")
        result = complete_partial_stage(
            source,
            self.library,
            book,
            "Author",
            "Title",
            inode_index,
            rel_target,
        )
        self.assertEqual(result.status, "name_collision")
        self.assertIn("name_collision", result.error or "")
        linked_after = analyze_book_staging(source, book, inode_index, library_root=self.library, staged_path_rel=rel_target)
        self.assertEqual(linked_after.linked_count, 2)

    def test_remove_extra_library_files(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(5, 5)
        extra = self.library / rel_target.replace("/", os.sep) / "old_track.mp3"
        extra.write_bytes(b"orphan")
        inode_index = build_inode_index(self.library)
        result = remove_extra_library_files(
            source,
            self.library,
            book,
            rel_target,
            inode_index,
        )
        self.assertEqual(result.status, "removed_extras")
        self.assertEqual(result.files_linked, 1)
        self.assertFalse(extra.exists())
        analysis = analyze_book_staging(
            source,
            book,
            inode_index,
            library_root=self.library,
            staged_path_rel=rel_target,
        )
        self.assertEqual(analysis.detail, "already_staged")
        self.assertEqual(len(analysis.extra_library_files), 0)

    def test_unstage_partial_removes_only_linked(self) -> None:
        book, source, inode_index, rel_target = self._link_partial(2, 5)
        result = unstage_book(source, self.library, book, rel_target)
        self.assertEqual(result.status, "unstaged")
        self.assertEqual(result.files_linked, 2)
        target_dir = self.library / rel_target.replace("/", os.sep)
        for af in book.files[:2]:
            self.assertFalse((target_dir / af.name).exists())
        for af in book.files[2:]:
            self.assertFalse((target_dir / af.name).exists())


if __name__ == "__main__":
    unittest.main()
