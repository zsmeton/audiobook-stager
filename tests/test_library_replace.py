from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from stager_core.staging import replace_library_target


class LibraryReplaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.library.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unlinks_audio_leaves_non_audio(self) -> None:
        target_dir = self.library / "Author" / "Title"
        target_dir.mkdir(parents=True)
        existing = target_dir / "existing.mp3"
        existing.write_bytes(b"x" * 100)
        cover = target_dir / "cover.jpg"
        cover.write_bytes(b"jpg")

        result = replace_library_target(self.library, "Author", "Title")
        self.assertEqual(result.status, "replaced")
        self.assertEqual(result.files_linked, 1)
        self.assertFalse(existing.exists())
        self.assertTrue(cover.is_file())

    def test_noop_when_target_missing(self) -> None:
        result = replace_library_target(self.library, "Author", "Title")
        self.assertEqual(result.status, "replaced")
        self.assertEqual(result.files_linked, 0)

    def test_unlink_hardlink_preserves_source(self) -> None:
        source = self.root / "seed.m4b"
        source.write_bytes(b"data")
        target_dir = self.library / "Author" / "Title"
        target_dir.mkdir(parents=True)
        link = target_dir / "book.m4b"
        os.link(source, link)

        result = replace_library_target(self.library, "Author", "Title")
        self.assertEqual(result.status, "replaced")
        self.assertEqual(result.files_linked, 1)
        self.assertTrue(source.is_file())
        self.assertFalse(link.exists())


if __name__ == "__main__":
    unittest.main()
