from __future__ import annotations

import unittest

from stager_core.metadata.effective import (
    any_chosen_set,
    chosen_series_state,
    effective_metadata,
    effective_series_state,
    target_key_preview,
)
from stager_core.staging import compute_target_key


class EffectiveMetadataTests(unittest.TestCase):
    def test_suggested_when_not_pinned(self) -> None:
        row = {
            "chosen_author": "",
            "chosen_title": "",
            "suggested_author": "Jane",
            "suggested_title": "Book",
            "chosen_author_set": 0,
            "chosen_title_set": 0,
        }
        eff = effective_metadata(row)
        self.assertEqual(eff["effective_author"], "Jane")
        self.assertEqual(eff["effective_title"], "Book")

    def test_chosen_series_state_unset(self) -> None:
        self.assertIsNone(chosen_series_state({"chosen_series_set": 0}))

    def test_chosen_series_state_confirmed(self) -> None:
        self.assertEqual(
            chosen_series_state({"chosen_series": "Saga", "chosen_series_set": 1}),
            "confirmed",
        )

    def test_pinned_empty_series_is_confirmed_none(self) -> None:
        row = {
            "chosen_series": "",
            "chosen_series_set": 1,
            "suggested_series": "Saga",
            "suggested_series_state": "confirmed",
        }
        self.assertEqual(effective_series_state(row), "confirmed_none")
        key = target_key_preview(
            {
                **row,
                "chosen_author": "A",
                "chosen_title": "T",
                "chosen_author_set": 1,
                "chosen_title_set": 1,
                "suggested_author": "",
                "suggested_title": "",
            }
        )
        self.assertEqual(key, compute_target_key("A", "T"))

    def test_any_chosen_set(self) -> None:
        self.assertTrue(any_chosen_set({"chosen_title_set": 1}))
        self.assertFalse(any_chosen_set({"chosen_title_set": 0, "chosen_author_set": 0}))

    def test_effective_series_falls_back_to_primary_candidate(self) -> None:
        row = {
            "chosen_series_set": 0,
            "chosen_series_index_set": 0,
            "suggested_series": "",
            "suggested_series_index": "",
            "suggested_series_state": "confirmed_none",
            "candidates_json": [
                {
                    "author": "Dennis E. Taylor",
                    "title": "Not Till We Are Lost",
                    "source": "audnexus",
                    "series": "Bobiverse",
                    "series_index": "5",
                    "in_winning_cluster": True,
                    "medoid_rank": 1,
                }
            ],
        }
        eff = effective_metadata(row)
        self.assertEqual(eff["effective_series"], "Bobiverse")
        self.assertEqual(eff["effective_series_index"], "5")
        self.assertEqual(eff["effective_series_state"], "confirmed")


if __name__ == "__main__":
    unittest.main()
