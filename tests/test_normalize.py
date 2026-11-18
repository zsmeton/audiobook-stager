from __future__ import annotations

import unittest

from stager_core.metadata.normalize import (
    clean_author,
    is_publisher_name,
    split_subtitle,
    strip_edition,
    strip_format_noise,
    strip_leading_index,
    strip_series_markers,
)


class StripLeadingIndexTests(unittest.TestCase):
    def test_strips_zero_padded_index(self) -> None:
        self.assertEqual(strip_leading_index("01 Red Rising"), "Red Rising")

    def test_strips_index_with_separator(self) -> None:
        self.assertEqual(strip_leading_index("1 - Red Rising"), "Red Rising")

    def test_leaves_bare_year(self) -> None:
        self.assertEqual(strip_leading_index("1984"), "1984")

    def test_leaves_year_prefixed_title(self) -> None:
        self.assertEqual(strip_leading_index("1177 B.C."), "1177 B.C.")

    def test_leaves_hyphenated_number(self) -> None:
        self.assertEqual(strip_leading_index("Catch-22"), "Catch-22")

    def test_leaves_ordinal_prefixed_title(self) -> None:
        self.assertEqual(
            strip_leading_index("10th Mountain Division Huts"),
            "10th Mountain Division Huts",
        )

    def test_leaves_non_numeric(self) -> None:
        self.assertEqual(strip_leading_index("The Six"), "The Six")

    def test_keeps_single_remaining_word(self) -> None:
        # Only one alpha word remains -> too risky, leave untouched.
        self.assertEqual(strip_leading_index("01 Intro"), "01 Intro")

    def test_strips_trailing_zero_padded_index(self) -> None:
        from stager_core.metadata.cleanup_pipeline import apply_pre_groups

        self.assertEqual(
            apply_pre_groups("The Heroes 01", frozenset({"index_trailing"})),
            "The Heroes",
        )

    def test_leaves_trailing_index_on_short_head(self) -> None:
        from stager_core.metadata.cleanup_pipeline import apply_pre_groups

        self.assertEqual(
            apply_pre_groups("Heroes 01", frozenset({"index_trailing"})),
            "Heroes 01",
        )

    def test_leading_index_does_not_strip_trailing(self) -> None:
        self.assertEqual(strip_leading_index("The Heroes 01"), "The Heroes 01")

    def test_leaves_area_51(self) -> None:
        self.assertEqual(strip_leading_index("Area 51"), "Area 51")


class StripEditionTests(unittest.TestCase):
    def test_removes_unabridged_parens(self) -> None:
        self.assertEqual(strip_edition("Red Rising (Unabridged)"), "Red Rising")

    def test_removes_bare_edition_word(self) -> None:
        self.assertEqual(strip_edition("Red Rising Unabridged"), "Red Rising")

    def test_removes_brackets(self) -> None:
        self.assertEqual(strip_edition("Red Rising [Dramatized]"), "Red Rising")


class StripFormatNoiseTests(unittest.TestCase):
    def test_removes_bitrate_and_codec(self) -> None:
        self.assertEqual(strip_format_noise("Red Rising 64kbps mp3"), "Red Rising")

    def test_keeps_bare_year_title(self) -> None:
        self.assertEqual(strip_format_noise("1984"), "1984")

    def test_removes_trailing_year(self) -> None:
        self.assertEqual(strip_format_noise("Red Rising 2014"), "Red Rising")


class StripSeriesMarkersTests(unittest.TestCase):
    def test_removes_book_number(self) -> None:
        self.assertEqual(strip_series_markers("Red Rising Book 1"), "Red Rising")

    def test_removes_hash_number(self) -> None:
        self.assertEqual(strip_series_markers("Red Rising #1"), "Red Rising")

    def test_removes_volume(self) -> None:
        self.assertEqual(strip_series_markers("Red Rising Vol. 2"), "Red Rising")


class CleanAuthorTests(unittest.TestCase):
    def test_drops_known_publisher(self) -> None:
        self.assertEqual(clean_author("Blackstone Audio"), "")
        self.assertEqual(clean_author("Tantor Audio"), "")
        self.assertEqual(clean_author("Graphic Audio"), "")

    def test_drops_narrator_in_parens(self) -> None:
        self.assertEqual(
            clean_author("Pierce Brown (Narrated by Tim Gerard Reynolds)"),
            "Pierce Brown",
        )

    def test_keeps_real_author(self) -> None:
        self.assertEqual(clean_author("Pierce Brown"), "Pierce Brown")

    def test_is_publisher_name(self) -> None:
        self.assertTrue(is_publisher_name("Tantor Audio"))
        self.assertTrue(is_publisher_name("Recorded Books"))
        self.assertFalse(is_publisher_name("Pierce Brown"))


class SubtitleSplitTests(unittest.TestCase):
    def test_splits_on_colon(self) -> None:
        self.assertEqual(split_subtitle("Red Rising: Book One"), ("Red Rising", "Book One"))

    def test_splits_on_dash(self) -> None:
        self.assertEqual(split_subtitle("Red Rising - Book One"), ("Red Rising", "Book One"))

    def test_no_subtitle(self) -> None:
        self.assertEqual(split_subtitle("Red Rising"), ("Red Rising", ""))


if __name__ == "__main__":
    unittest.main()
