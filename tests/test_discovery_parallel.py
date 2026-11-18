from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stager_core.discovery import discover_books


class DiscoveryParallelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for idx in range(3):
            book_dir = self.root / f"Author {idx}" / f"Title {idx}"
            book_dir.mkdir(parents=True)
            (book_dir / "book.m4b").write_bytes(bytes([idx]) * 128)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parallel_fingerprint_matches_serial(self) -> None:
        serial = discover_books(self.root, fingerprint_workers=1)
        parallel = discover_books(self.root, fingerprint_workers=4)
        self.assertEqual(len(serial), len(parallel))
        serial_by_id = {book.id: book for book in serial}
        parallel_by_id = {book.id: book for book in parallel}
        self.assertEqual(set(serial_by_id), set(parallel_by_id))
        for book_id, book in serial_by_id.items():
            other = parallel_by_id[book_id]
            self.assertEqual(book.flatten_target, other.flatten_target)
            self.assertEqual(book.source_path, other.source_path)
            self.assertEqual(len(book.files), len(other.files))
