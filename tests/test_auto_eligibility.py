from __future__ import annotations

import unittest

from stager_core.auto_eligibility import is_eligible_for_auto_stage


def _book(**kwargs) -> dict:
    base = {
        "id": "abc",
        "status": "pending",
        "confidence": 0.95,
        "chosen_author": "",
        "chosen_title": "",
        "suggested_author": "Author",
        "suggested_title": "Title",
    }
    base.update(kwargs)
    return base


class AutoEligibilityTests(unittest.TestCase):
    def test_eligible_high_confidence(self) -> None:
        self.assertTrue(is_eligible_for_auto_stage(_book(), set(), 0.9))

    def test_excluded_low_confidence(self) -> None:
        self.assertFalse(is_eligible_for_auto_stage(_book(confidence=0.85), set(), 0.9))

    def test_excluded_conflict(self) -> None:
        self.assertFalse(is_eligible_for_auto_stage(_book(), {"abc"}, 0.9))

    def test_excluded_partial_staged_status(self) -> None:
        self.assertFalse(is_eligible_for_auto_stage(_book(status="partial_staged"), set(), 0.9))

    def test_excluded_missing_author(self) -> None:
        self.assertFalse(
            is_eligible_for_auto_stage(
                _book(suggested_author="", suggested_title="Title"),
                set(),
                0.9,
            )
        )

    def test_excluded_when_author_pinned(self) -> None:
        self.assertFalse(
            is_eligible_for_auto_stage(
                _book(chosen_author_set=1, chosen_author="Pinned"),
                set(),
                0.9,
            )
        )

    def test_eligible_from_suggested_only(self) -> None:
        self.assertTrue(
            is_eligible_for_auto_stage(
                _book(
                    chosen_author="",
                    chosen_title="",
                    suggested_author="A",
                    suggested_title="T",
                ),
                set(),
                0.9,
            )
        )


if __name__ == "__main__":
    unittest.main()
