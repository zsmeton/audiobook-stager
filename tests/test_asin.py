from __future__ import annotations

import unittest

from stager_core.metadata.tags import (
    _extract_asin_from_trusted_fields,
    extract_asin,
)


class ExtractAsinTests(unittest.TestCase):
    def test_rejects_all_letter_lookalikes(self) -> None:
        self.assertEqual(extract_asin("BLACKSTONE"), "")
        self.assertEqual(extract_asin("BLOOMSBURY"), "")
        self.assertEqual(extract_asin("BUCKINGHAM"), "")

    def test_accepts_real_asin(self) -> None:
        self.assertEqual(extract_asin("B00ABCD123"), "B00ABCD123")
        self.assertEqual(extract_asin("asin: B0024CEZGG"), "B0024CEZGG")

    def test_requires_leading_b(self) -> None:
        self.assertEqual(extract_asin("A0024CEZGG"), "")

    def test_requires_two_digits(self) -> None:
        # Only one digit -> rejected.
        self.assertEqual(extract_asin("BLACKSTON1"), "")


class TrustedFieldTests(unittest.TestCase):
    def test_ignores_arbitrary_artist_tag(self) -> None:
        tags = {"artist": ["B0024CEZGG"]}
        self.assertEqual(_extract_asin_from_trusted_fields(tags, ""), "")

    def test_trusts_asin_field(self) -> None:
        tags = {"artist": ["B0024CEZGG"], "asin": ["B0034ABCD1"]}
        self.assertEqual(_extract_asin_from_trusted_fields(tags, ""), "B0034ABCD1")

    def test_trusts_comment_argument(self) -> None:
        tags = {"artist": ["BLACKSTONE"]}
        self.assertEqual(
            _extract_asin_from_trusted_fields(tags, "audible asin B0024CEZGG"),
            "B0024CEZGG",
        )

    def test_trusts_audible_keyed_field(self) -> None:
        tags = {"audible_asin": ["B0099XYZ12"]}
        self.assertEqual(_extract_asin_from_trusted_fields(tags, ""), "B0099XYZ12")


if __name__ == "__main__":
    unittest.main()
