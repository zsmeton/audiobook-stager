"""D06 media-kind seam. Audiobook is the only kind. No ebook parser."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stager_core.discovery import discover_books
from stager_core.media_kind import UnknownMediaKind, get_kind, implemented_kinds
from stager_core.metadata.tags import read_tags
from stager_core.metadata.types import TagInfo


class MediaKindSeamTests(unittest.TestCase):
    def test_only_implemented_kind_is_audiobook(self) -> None:
        self.assertEqual(implemented_kinds(), ("audiobook",))
        kind = get_kind("audiobook")
        self.assertEqual(kind.name, "audiobook")
        self.assertNotIn(".epub", kind.extensions())
        self.assertNotIn(".mobi", kind.extensions())

    def test_ebook_kind_does_not_parse_a_file(self) -> None:
        calls: list[str] = []
        real_open = Path.open
        real_read_bytes = Path.read_bytes
        real_is_file = Path.is_file
        real_stat = Path.stat

        def track_open(self, *args, **kwargs):
            calls.append(f"open:{self.name}")
            return real_open(self, *args, **kwargs)

        def track_read_bytes(self, *args, **kwargs):
            calls.append(f"read_bytes:{self.name}")
            return real_read_bytes(self, *args, **kwargs)

        def track_is_file(self, *args, **kwargs):
            calls.append(f"is_file:{self.name}")
            return real_is_file(self, *args, **kwargs)

        def track_stat(self, *args, **kwargs):
            calls.append(f"stat:{self.name}")
            return real_stat(self, *args, **kwargs)

        def track_mutagen(*args, **kwargs):
            calls.append("mutagen")
            raise AssertionError("mutagen parsed a file")

        def track_reader(path: Path) -> TagInfo:
            calls.append(f"reader:{path.name}")
            raise AssertionError("audiobook reader parsed a file")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epub = root / "Novel.epub"
            mobi = root / "Novel.mobi"
            epub.write_bytes(b"PK\x03\x04not-an-audiobook")
            mobi.write_bytes(b"BOOKMOBInot-an-audiobook")
            with (
                patch.object(Path, "open", track_open),
                patch.object(Path, "read_bytes", track_read_bytes),
                patch.object(Path, "is_file", track_is_file),
                patch.object(Path, "stat", track_stat),
                patch("mutagen.File", track_mutagen),
                patch("stager_core.metadata.tags.read_audiobook_tags", track_reader),
            ):
                for kind, path in (("ebook", epub), ("epub", epub), ("mobi", mobi)):
                    with self.assertRaises(UnknownMediaKind) as caught:
                        get_kind(kind).read_tags(path)
                    self.assertEqual(caught.exception.kind, kind)
                    with self.assertRaises(UnknownMediaKind):
                        get_kind(kind).matches(path)
            self.assertEqual(calls, [])
            self.assertEqual(epub.read_bytes(), b"PK\x03\x04not-an-audiobook")
            self.assertEqual(mobi.read_bytes(), b"BOOKMOBInot-an-audiobook")

    def test_discovery_and_tag_reads_call_the_audiobook_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "Red Rising"
            book.mkdir()
            mp3 = book / "chapter.mp3"
            mp3.write_bytes(b"")
            (book / "bonus.epub").write_bytes(b"PK\x03\x04")

            seen: list[str] = []
            real_get = get_kind

            def spy(name: str):
                seen.append(name)
                return real_get(name)

            with patch("stager_core.discovery.get_kind", spy):
                books = discover_books(root)
            self.assertEqual(seen, ["audiobook"] * len(seen))
            self.assertGreaterEqual(len(seen), 1)
            self.assertEqual(len(books), 1)
            self.assertEqual([f.name for f in books[0].files], ["chapter.mp3"])

            seen.clear()
            with patch("stager_core.metadata.tags.get_kind", spy):
                info = read_tags(mp3)
            self.assertEqual(seen, ["audiobook"])
            self.assertIsInstance(info, TagInfo)
            self.assertEqual(info.title, "")
