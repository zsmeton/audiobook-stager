from __future__ import annotations

import unittest

from stager_core.staging import (
    compute_target_key,
    format_title_folder,
    resolve_staging_target,
)


class SeriesStagingTests(unittest.TestCase):
    def test_two_level_without_series(self) -> None:
        key = compute_target_key("Author Name", "Book Title")
        self.assertEqual(key, "Author Name/Book Title")

    def test_three_level_with_index(self) -> None:
        key = compute_target_key("Author", "Title", "Saga", "3")
        self.assertEqual(key, "Author/Saga/3 - Title")

    def test_format_title_folder(self) -> None:
        self.assertEqual(format_title_folder("My Book", "2"), "2 - My Book")
        self.assertEqual(format_title_folder("My Book"), "My Book")

    def test_resolve_staging_target_three_level(self) -> None:
        from pathlib import Path

        target_dir, author_dir, rel_suffix = resolve_staging_target(
            Path("/lib"), "Author", "Title", "Series", "1"
        )
        self.assertEqual(author_dir, "Author")
        self.assertEqual(rel_suffix, "Series/1 - Title")
        self.assertEqual(str(target_dir).replace("\\", "/"), "/lib/Author/Series/1 - Title")


if __name__ == "__main__":
    unittest.main()
