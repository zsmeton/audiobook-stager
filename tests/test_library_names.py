from __future__ import annotations

import unittest

from app.api import _library_names_from_path


class LibraryNamesTests(unittest.TestCase):
    def test_splits_author_and_title(self) -> None:
        self.assertEqual(
            _library_names_from_path("Pierce Brown/Dark Age"),
            ("Pierce Brown", "Dark Age"),
        )

    def test_empty_path(self) -> None:
        self.assertEqual(_library_names_from_path(""), ("", ""))

    def test_title_only(self) -> None:
        self.assertEqual(_library_names_from_path("Title Only"), ("", "Title Only"))


if __name__ == "__main__":
    unittest.main()
