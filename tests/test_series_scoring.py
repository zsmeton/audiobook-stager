from __future__ import annotations

import unittest

from stager_core.metadata.scoring import Evidence, pick_winner
from stager_core.metadata.series_scoring import (
    SeriesVote,
    annotate_series_membership,
    fold_staging_confidence,
    pick_series,
    pick_series_votes_from_cluster,
    series_family,
)
from stager_core.metadata.types import MetadataCandidate


class SeriesScoringTests(unittest.TestCase):
    def test_mam_only_capped_at_fifty_percent(self) -> None:
        _series, _index, conf, state, breakdown = pick_series(
            [SeriesVote(family="mam", series="Red Rising", series_index="1")]
        )
        self.assertEqual(conf, 0.50)
        self.assertEqual(state, "confirmed")
        self.assertIn("single_source_series_cap", breakdown["caps_applied"])

    def test_mam_and_audible_agree_high_confidence(self) -> None:
        _series, _index, conf, _state, _breakdown = pick_series(
            [
                SeriesVote(family="mam", series="Red Rising", series_index="1"),
                SeriesVote(family="audible", series="Red Rising", series_index="1"),
            ]
        )
        self.assertGreater(conf, 0.90)

    def test_fuzzy_cluster_picks_medoid(self) -> None:
        series, _index, _conf, _state, _breakdown = pick_series(
            [
                SeriesVote(family="mam", series="Ender's Shadow", series_index="1"),
                SeriesVote(family="audible", series="Enders Shadow", series_index="1"),
            ]
        )
        self.assertIn("Shadow", series)

    def test_series_family_sources(self) -> None:
        self.assertEqual(series_family("audnexus"), "audnexus")
        self.assertEqual(series_family("audible"), "audible")
        self.assertEqual(series_family("mam"), "mam")
        self.assertEqual(series_family("id3_series"), "id3_series")
        self.assertEqual(series_family("title_first"), "title_first")
        self.assertEqual(series_family("author_oeuvre"), "author_oeuvre")
        self.assertEqual(series_family("google_books"), "")

    def test_title_first_and_oeuvre_corroborate_series(self) -> None:
        author = "Dennis E. Taylor"
        title = "All These Worlds"
        candidates = [
            MetadataCandidate(
                author=author,
                title=title,
                source="title_first",
                confidence=0.0,
                series="Bobiverse",
                series_index="3",
            ),
            MetadataCandidate(
                author=author,
                title=title,
                source="audible",
                confidence=0.0,
                series="Bobiverse",
                series_index="3",
            ),
            MetadataCandidate(
                author=author,
                title=title,
                source="author_oeuvre",
                confidence=0.0,
                series="Bobiverse",
                series_index="3",
            ),
            MetadataCandidate(
                author=author,
                title="All These Worlds: Bobiverse",
                source="id3",
                confidence=0.0,
            ),
        ]
        evidence = [
            Evidence(c.source, c.author, c.title, extras={"candidate": c})
            for c in candidates
        ]
        _, breakdown = pick_winner(evidence)
        votes = pick_series_votes_from_cluster(breakdown, candidates)
        families = {v.family for v in votes}
        self.assertEqual(
            families,
            {"title_first", "audible", "author_oeuvre"},
        )
        _series, index, conf, state, sbd = pick_series(votes)
        self.assertEqual(_series, "Bobiverse")
        self.assertEqual(index, "3")
        self.assertGreater(conf, 0.90)
        self.assertEqual(state, "confirmed")
        self.assertNotIn("single_source_series_cap", sbd["caps_applied"])
        staging, _ = fold_staging_confidence(breakdown["confidence"], conf, state)
        self.assertGreater(staging, 0.90)

    def test_empty_votes_win_confirmed_none(self) -> None:
        _series, _index, conf, state, _breakdown = pick_series(
            [
                SeriesVote(family="audible", series="", series_index=""),
                SeriesVote(family="mam", series="", series_index=""),
            ]
        )
        self.assertEqual(state, "confirmed_none")
        self.assertEqual(conf, 1.0)

    def test_missing_index_cap(self) -> None:
        _series, _index, conf, _state, breakdown = pick_series(
            [
                SeriesVote(family="mam", series="Red Rising", series_index=""),
                SeriesVote(family="audible", series="Red Rising", series_index=""),
            ]
        )
        self.assertLessEqual(conf, 0.70)
        self.assertIn("missing_index_cap", breakdown["caps_applied"])

    def test_fold_skips_series_leg_on_confirmed_none(self) -> None:
        staging, breakdown = fold_staging_confidence(0.94, 0.40, "confirmed_none")
        self.assertEqual(staging, 0.94)
        self.assertEqual(breakdown["series_state"], "confirmed_none")

    def test_fold_min_when_series_present(self) -> None:
        staging, _breakdown = fold_staging_confidence(0.94, 0.80, "confirmed")
        self.assertEqual(staging, 0.80)

    def test_annotate_mam_only_series_capped_at_fifty(self) -> None:
        candidates = [
            MetadataCandidate(
                author="A",
                title="T",
                source="mam",
                confidence=0.85,
                series="Red Rising",
            ),
            MetadataCandidate(
                author="A",
                title="T",
                source="audible",
                confidence=0.9,
                series="Red Rising",
            ),
        ]
        _, _, _, _, breakdown = pick_series(
            [SeriesVote(family="mam", series="Red Rising", series_index="1")]
        )
        annotate_series_membership(candidates, breakdown)
        self.assertAlmostEqual(candidates[0].series_membership, 0.50)
        self.assertEqual(candidates[1].series_membership, 0.0)

    def test_annotate_series_membership_from_winning_votes(self) -> None:
        candidates = [
            MetadataCandidate(
                author="A",
                title="T",
                source="audible",
                confidence=0.9,
                series="Red Rising",
            ),
            MetadataCandidate(
                author="A",
                title="T",
                source="mam",
                confidence=0.85,
                series="Red Rising",
            ),
            MetadataCandidate(
                author="A",
                title="T",
                source="id3_series",
                confidence=0.65,
                series="Other",
            ),
        ]
        _, _, _, _, breakdown = pick_series(
            [
                SeriesVote(family="mam", series="Red Rising", series_index="1"),
                SeriesVote(family="audible", series="Red Rising", series_index="1"),
            ]
        )
        annotate_series_membership(candidates, breakdown)
        self.assertGreater(candidates[0].series_membership, 0.50)
        self.assertGreater(candidates[1].series_membership, 0.50)
        self.assertEqual(candidates[2].series_membership, 0.0)

    def test_annotate_id3_series_only_when_in_winning_cluster(self) -> None:
        candidates = [
            MetadataCandidate(
                author="A",
                title="T",
                source="id3_series",
                confidence=0.65,
                series="Red Rising",
            ),
        ]
        _, _, _, _, breakdown = pick_series(
            [
                SeriesVote(family="id3_series", series="Red Rising", series_index=""),
                SeriesVote(family="mam", series="Red Rising", series_index="1"),
            ]
        )
        annotate_series_membership(candidates, breakdown)
        self.assertAlmostEqual(candidates[0].series_membership, 0.65)


if __name__ == "__main__":
    unittest.main()
