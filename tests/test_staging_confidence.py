from __future__ import annotations

import unittest

from stager_core.metadata.series_scoring import fold_staging_confidence


class StagingConfidenceTests(unittest.TestCase):
    def test_confirmed_none_uses_book_leg_only(self) -> None:
        staging, breakdown = fold_staging_confidence(0.91, 0.0, "confirmed_none")
        self.assertEqual(staging, 0.91)
        self.assertEqual(breakdown["book_leg"], 0.91)

    def test_named_series_uses_min(self) -> None:
        staging, breakdown = fold_staging_confidence(0.95, 0.72, "confirmed")
        self.assertEqual(staging, 0.72)
        self.assertEqual(breakdown["series_leg"], 0.72)


if __name__ == "__main__":
    unittest.main()
