from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stager_core.discovery import discover_books


class ScanBooksFoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.books_root.mkdir()
        (self.books_root / "Author" / "Title").mkdir(parents=True)
        (self.books_root / "Author" / "Title" / "book.m4b").write_bytes(b"x" * 100)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_discovery_on_progress_reports_book_count(self) -> None:
        counts: list[int] = []
        books = discover_books(self.books_root, on_progress=counts.append, progress_interval=1)
        self.assertEqual(len(books), 1)
        self.assertEqual(counts[-1], 1)

    @patch.dict(
        os.environ,
        {
            "GOOGLE_BOOKS_API_KEY": "",
            "STAGER_MAM_ID": "",
            "STAGER_MAM_COOKIE_FILE": r"Z:\__no_stager_mam_cookies__",
        },
        clear=False,
    )
    def test_provider_list_env(self) -> None:
        from stager_core.metadata.provider_registry import list_provider_status

        items = {p["id"]: p for p in list_provider_status()}
        self.assertFalse(items["google_books"]["configured"])
        self.assertFalse(items["mam"]["configured"])
