from __future__ import annotations

import unittest

from stager_core.metadata.scoring import (
    Evidence,
    membership_grade,
    pick_winner,
)


def _ev(source: str, author: str, title: str, **extras) -> Evidence:
    return Evidence(source=source, author=author, title=title, extras=extras)


class MembershipGradeTests(unittest.TestCase):
    def test_full_member(self) -> None:
        self.assertEqual(membership_grade(0.95), 1.0)
        self.assertEqual(membership_grade(0.88), 1.0)

    def test_weak_member_ramps(self) -> None:
        grade = membership_grade(0.80)
        self.assertGreater(grade, 0.5)
        self.assertLess(grade, 1.0)

    def test_below_threshold(self) -> None:
        self.assertEqual(membership_grade(0.70), 0.0)


class PickWinnerTests(unittest.TestCase):
    def test_mam_and_audnexus_agree_high(self) -> None:
        evidence = [
            _ev("mam", "Pierce Brown", "Red Rising"),
            _ev("audnexus", "Pierce Brown", "Red Rising"),
        ]
        _, breakdown = pick_winner(evidence)
        self.assertGreaterEqual(breakdown["confidence"], 0.90)
        self.assertEqual(breakdown["status"], "ok")

    def test_junk_id3_only_capped(self) -> None:
        evidence = [_ev("id3", "Unknown", "Mystery Manuscript")]
        _, breakdown = pick_winner(evidence)
        self.assertLessEqual(breakdown["confidence"], 0.65)

    def test_conflicting_clusters_ambiguous(self) -> None:
        evidence = [
            _ev("mam", "Pierce Brown", "Red Rising"),
            _ev("audnexus", "Frank Herbert", "Dune"),
        ]
        _, breakdown = pick_winner(evidence)
        self.assertEqual(breakdown["status"], "ambiguous")
        self.assertEqual(breakdown["representative"]["source"], "mam")
        self.assertLessEqual(breakdown["confidence"], 0.55)

    def test_mam_exact_alone(self) -> None:
        evidence = [_ev("mam_exact", "Pierce Brown", "Red Rising")]
        _, breakdown = pick_winner(evidence)
        self.assertAlmostEqual(breakdown["confidence"], 0.95)

    def test_tags_and_path_agree_separate_families(self) -> None:
        evidence = [
            _ev("id3", "Pierce Brown", "Red Rising"),
            _ev("folder", "Pierce Brown", "Red Rising"),
        ]
        _, breakdown = pick_winner(evidence)
        # id3 -> tags, folder -> path: two independent local families corroborate.
        self.assertIn("tags", breakdown["families"])
        self.assertIn("path", breakdown["families"])
        # Noisy-OR rises above 0.65 (1-(0.35*0.35)=0.8775)...
        self.assertGreater(breakdown["raw_confidence"], 0.65)
        # ...but the flat local-only cap still holds at 0.65.
        self.assertEqual(breakdown["confidence"], 0.65)

    def test_tags_and_path_disagree_one_joins_winner(self) -> None:
        evidence = [
            _ev("id3", "Pierce Brown", "Red Rising"),
            _ev("folder", "Frank Herbert", "Dune"),
        ]
        _, breakdown = pick_winner(evidence)
        winning_local = set(breakdown["families"]) & {"tags", "path"}
        self.assertEqual(len(winning_local), 1)
        self.assertLessEqual(breakdown["confidence"], 0.65)

    def test_external_plus_tags_reaches_gate(self) -> None:
        evidence = [
            _ev("audnexus", "Pierce Brown", "Red Rising"),
            _ev("id3", "Pierce Brown", "Red Rising"),
        ]
        _, breakdown = pick_winner(evidence)
        # 1-(0.20*0.35)=0.93, external present so no local-only cap.
        self.assertGreaterEqual(breakdown["confidence"], 0.90)
        self.assertIn("tags", breakdown["families"])
        self.assertIn("audnexus", breakdown["families"])

    def test_weak_corroborator_contributes_less_than_full(self) -> None:
        single = pick_winner([_ev("audnexus", "Pierce Brown", "The Red Planet")])[1][
            "confidence"
        ]
        full = pick_winner(
            [
                _ev("audnexus", "Pierce Brown", "The Red Planet"),
                _ev("google_books", "Pierce Brown", "The Red Planet"),
            ]
        )[1]["confidence"]
        weak = pick_winner(
            [
                _ev("audnexus", "Pierce Brown", "The Red Planet"),
                _ev("google_books", "Pierce Brown", "Red Planet Mars"),
            ]
        )[1]["confidence"]
        self.assertGreater(full, weak)
        self.assertGreater(weak, single)

    def test_no_evidence(self) -> None:
        winner, breakdown = pick_winner([])
        self.assertIsNone(winner)
        self.assertEqual(breakdown["status"], "no_match")

    def test_winner_candidate_carries_breakdown(self) -> None:
        from stager_core.metadata.types import MetadataCandidate

        cand = MetadataCandidate(author="Pierce Brown", title="Red Rising", source="mam", confidence=0.0)
        ev = Evidence(source="mam", author="Pierce Brown", title="Red Rising", extras={"candidate": cand})
        winner, breakdown = pick_winner([ev])
        self.assertIs(winner, cand)
        self.assertEqual(cand.score_breakdown, breakdown)
        self.assertGreater(cand.confidence, 0.0)

    def test_medoid_picks_consensus_over_seed(self) -> None:
        from stager_core.metadata.types import MetadataCandidate

        author = "Dr. Anna Lembke"
        consensus = "Dopamine Nation: Finding Balance in the Age of Indulgence"
        noisy_seed = (
            "Dopamine Nation: Finding Balance in the Age of Indulgence "
            "| डोपामाइन नेशन: भोग के युग में संतुलन की तलाश"
        )

        def cand(source: str, title: str) -> Evidence:
            c = MetadataCandidate(author=author, title=title, source=source, confidence=0.0)
            return _ev(source, author, title, candidate=c)

        evidence = [
            cand("google_books", noisy_seed),
            cand("google_books", consensus),
            cand("id3", consensus),
            cand("filename", consensus),
            cand("folder", consensus),
        ]
        winner, breakdown = pick_winner(evidence)
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner.title, consensus)
        self.assertNotIn("डोपामाइन", breakdown["representative"]["title"])

    def test_medoid_preserves_multilingual_winner(self) -> None:
        author = "Some Author"
        hindi = "डोपामाइन नेशन"
        evidence = [
            _ev("google_books", author, hindi),
            _ev("id3", author, hindi),
            _ev("folder", author, hindi),
        ]
        _, breakdown = pick_winner(evidence)
        self.assertIn(hindi, breakdown["representative"]["title"])

    def test_workbook_does_not_merge_main_cluster(self) -> None:
        author = "Dr. Anna Lembke"
        main = "Dopamine Nation: Finding Balance in the Age of Indulgence"
        evidence = [
            _ev("google_books", author, main),
            _ev("id3", author, main),
            _ev("google_books", author, "The Official Dopamine Nation Workbook"),
        ]
        _, breakdown = pick_winner(evidence)
        pool = breakdown["evidence_pool"]
        main_cluster = next(e["cluster_id"] for e in pool if e["source"] == "id3")
        workbook_cluster = next(
            e["cluster_id"]
            for e in pool
            if e["source"] == "google_books" and "Workbook" in e["title"]
        )
        self.assertNotEqual(main_cluster, workbook_cluster)
        self.assertEqual(breakdown["status"], "ok")
        self.assertGreater(breakdown["confidence"], 0.55)

    def test_winning_cluster_members_get_cluster_and_centrality(self) -> None:
        from stager_core.metadata.lookup import annotate_candidates
        from stager_core.metadata.types import MetadataCandidate

        author = "Adrian Goldsworthy"
        short = "Athens and Sparta"
        full = "Athens and Sparta: The Rivalry That Shaped Ancient Greece"

        def cand(source: str, title: str) -> MetadataCandidate:
            return MetadataCandidate(author=author, title=title, source=source, confidence=0.0)

        candidates = [
            cand("audnexus", short),
            cand("google_books", short),
            cand("id3", full),
            cand("folder", "Adrian Goldsworthy - Athens and Sparta"),
        ]
        evidence = [
            _ev("audnexus", author, short, candidate=candidates[0]),
            _ev("google_books", author, short, candidate=candidates[1]),
            _ev("id3", author, full, candidate=candidates[2]),
            _ev("folder", author, "Adrian Goldsworthy - Athens and Sparta", candidate=candidates[3]),
        ]
        winner, breakdown = pick_winner(evidence)
        annotate_candidates(candidates, breakdown)
        self.assertIs(winner, candidates[0])
        self.assertEqual(candidates[0].medoid_rank, 1)
        self.assertGreater(candidates[0].medoid_score, candidates[3].medoid_score)
        self.assertEqual(candidates[0].confidence, breakdown["confidence"])
        self.assertEqual(candidates[0].cluster_confidence, breakdown["confidence"])
        self.assertGreater(candidates[2].cluster_confidence, 0.0)
        self.assertGreater(candidates[2].medoid_score, 0.0)

    def test_non_winning_cluster_gets_cluster_confidence(self) -> None:
        from stager_core.metadata.lookup import annotate_candidates
        from stager_core.metadata.types import MetadataCandidate

        author = "Dr. Anna Lembke"
        main = "Dopamine Nation: Finding Balance in the Age of Indulgence"

        def cand(source: str, title: str) -> MetadataCandidate:
            return MetadataCandidate(author=author, title=title, source=source, confidence=0.0)

        candidates = [
            cand("google_books", main),
            cand("id3", main),
            cand("google_books", "The Official Dopamine Nation Workbook"),
        ]
        evidence = [
            _ev("google_books", author, main, candidate=candidates[0]),
            _ev("id3", author, main, candidate=candidates[1]),
            _ev("google_books", author, "The Official Dopamine Nation Workbook", candidate=candidates[2]),
        ]
        _, breakdown = pick_winner(evidence)
        annotate_candidates(candidates, breakdown)
        workbook = candidates[2]
        self.assertFalse(workbook.in_winning_cluster)
        self.assertGreater(workbook.cluster_confidence, 0.0)
        self.assertGreater(workbook.medoid_score, 0.0)
        self.assertEqual(workbook.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
