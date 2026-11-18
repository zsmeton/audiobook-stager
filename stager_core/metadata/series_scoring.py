"""Series name consensus within the winning author/title cluster.



Uses the same fuzzy-cluster + bounded noisy-OR pattern as ``scoring.py``,

with caps so a single provider or missing index cannot overstate confidence.

"""



from __future__ import annotations



from dataclasses import dataclass

from difflib import SequenceMatcher



from stager_core.metadata.scoring import (

    POSSIBLE_BOOK_THRESHOLD,

    membership_grade,

)



# ============================== CONFIG (tunables) ==============================

SERIES_FAMILY_PRIORS: dict[str, float] = {

    "audible": 0.80,

    "mam": 0.85,

    "audnexus": 0.80,

    "author_oeuvre": 0.85,

    "title_first": 0.75,

    "id3_series": 0.65,
    "library": 0.80,

}

SINGLE_SOURCE_SERIES_CAP = 0.50

SERIES_MISSING_INDEX_CAP = 0.70

# ==============================================================================



_EMPTY_CLUSTER_KEY = "__none__"





@dataclass

class SeriesVote:

    """Raw series signal from one provider before clustering."""



    family: str

    series: str

    series_index: str = ""





def series_family(source: str) -> str:

    """Map candidate source string to a series scoring family."""

    if source in SERIES_FAMILY_PRIORS:

        return source

    return ""





def series_sim(a: str, b: str) -> bool | float:

    """Compare series names; empty strings match only each other."""

    a = (a or "").strip()

    b = (b or "").strip()

    if not a and not b:

        return 1.0

    if not a or not b:

        return 0.0

    na = " ".join(a.lower().split())

    nb = " ".join(b.lower().split())

    ta, tb = set(na.split()), set(nb.split())

    token = len(ta & tb) / len(ta | tb) if ta and tb else 0.0

    seq = SequenceMatcher(None, na, nb).ratio()

    return max(token, seq)





def _noisy_or(supports: dict[str, float]) -> float:

    product = 1.0

    for support in supports.values():

        product *= 1.0 - support

    return 1.0 - product





@dataclass

class _SeriesMember:

    vote: SeriesVote

    membership: float





@dataclass

class _SeriesCluster:

    members: list[_SeriesMember]

    is_empty: bool = False



    @property

    def representative(self) -> SeriesVote:

        return self.members[0].vote





def _cluster_series(votes: list[SeriesVote]) -> list[_SeriesCluster]:

    ordered = sorted(

        votes,

        key=lambda v: SERIES_FAMILY_PRIORS.get(v.family, 0.0),

        reverse=True,

    )

    clusters: list[_SeriesCluster] = []

    for vote in ordered:

        best_cluster: _SeriesCluster | None = None

        best_sim = 0.0

        for cluster in clusters:

            sim = series_sim(cluster.representative.series, vote.series)

            if isinstance(sim, float) and sim >= POSSIBLE_BOOK_THRESHOLD and sim > best_sim:

                best_sim = sim

                best_cluster = cluster

        if best_cluster is not None:

            best_cluster.members.append(

                _SeriesMember(vote, membership_grade(best_sim))

            )

        else:

            clusters.append(

                _SeriesCluster(

                    members=[_SeriesMember(vote, 1.0)],

                    is_empty=not (vote.series or "").strip(),

                )

            )

    return clusters





def _family_support(cluster: _SeriesCluster) -> dict[str, float]:

    """Best prior × membership per family in the series cluster."""

    families: dict[str, float] = {}

    for member in cluster.members:

        prior = SERIES_FAMILY_PRIORS.get(member.vote.family, 0.0)

        support = prior * member.membership

        families[member.vote.family] = max(families.get(member.vote.family, 0.0), support)

    return families





def _pick_medoid(cluster: _SeriesCluster) -> SeriesVote:

    members = cluster.members

    if len(members) == 1:

        return members[0].vote

    best = members[0]

    best_score = -1.0

    for member in members:

        others = [m for m in members if m is not member]

        if not others:

            score = 1.0

        else:

            score = sum(

                float(series_sim(member.vote.series, o.vote.series) or 0.0)

                for o in others

            ) / len(others)

        if score > best_score:

            best_score = score

            best = member

    return best.vote





def _best_index_for_series(cluster: _SeriesCluster, series_name: str) -> str:

    best_idx = ""

    best_sim = 0.0

    for member in cluster.members:

        if not member.vote.series_index:

            continue

        sim = float(series_sim(member.vote.series, series_name) or 0.0)

        if sim > best_sim:

            best_sim = sim

            best_idx = member.vote.series_index

    return best_idx





def _winning_series_source(families: dict[str, float]) -> str:

    if not families:

        return ""

    ordered = sorted(families.items(), key=lambda item: (-item[1], item[0]))

    return "consensus:" + "+".join(name for name, _ in ordered)





def fold_staging_confidence(

    book_leg: float,

    series_leg: float,

    series_state: str,

) -> tuple[float, dict]:

    """Return staging confidence and breakdown dict."""

    book_leg = round(min(1.0, max(0.0, float(book_leg or 0))), 4)

    series_leg = round(min(1.0, max(0.0, float(series_leg or 0))), 4)

    if series_state == "confirmed_none":

        staging = book_leg

    else:

        staging = min(book_leg, series_leg)

    return round(staging, 4), {

        "book_leg": book_leg,

        "series_leg": series_leg,

        "staging_confidence": round(staging, 4),

        "series_state": series_state,

    }





def pick_series(

    votes: list[SeriesVote],

) -> tuple[str, str, float, str, dict]:

    """Return ``(series, index, confidence, state, breakdown)``.



    ``votes`` should already be scoped to the winning author/title cluster

    (plus optional id3_series). Empty-string votes compete in the same fuzzy

    cluster as named series.

    """

    if not votes:

        return "", "", 0.0, "unknown", {"status": "no_votes", "confidence": 0.0, "votes": []}



    clusters = _cluster_series(votes)

    scored = sorted(

        clusters,

        key=lambda c: (_noisy_or(_family_support(c)), len(c.members)),

        reverse=True,

    )

    winner = scored[0]

    families = _family_support(winner)

    raw_conf = _noisy_or(families)

    caps: list[str] = []



    if winner.is_empty or not (winner.representative.series or "").strip():

        state = "confirmed_none"

        conf = 1.0

        series_name = ""

        series_index = ""

    else:

        state = "confirmed"

        if len(families) < 2:

            conf = min(raw_conf, SINGLE_SOURCE_SERIES_CAP)

            caps.append("single_source_series_cap")

        else:

            conf = raw_conf

        rep = _pick_medoid(winner)

        series_name = rep.series.strip()

        series_index = _best_index_for_series(winner, series_name)

        if series_name and not series_index:

            conf = min(conf, SERIES_MISSING_INDEX_CAP)

            caps.append("missing_index_cap")



    breakdown = {

        "status": "confirmed_none" if state == "confirmed_none" else "ok",

        "confidence": round(min(1.0, max(0.0, conf)), 4),

        "raw_confidence": round(raw_conf, 4),

        "state": state,

        "series": series_name,

        "series_index": series_index,

        "families": {k: round(v, 4) for k, v in families.items()},

        "caps_applied": caps,

        "cluster_size": len(winner.members),

        "winning_source": _winning_series_source(families),

        "votes": [

            {

                "family": m.vote.family,

                "series": m.vote.series,

                "series_index": m.vote.series_index,

                "membership": round(m.membership, 4),

            }

            for m in winner.members

        ],

    }

    return series_name, series_index, breakdown["confidence"], state, breakdown





def pick_series_votes_from_cluster(

    score_breakdown: dict,

    candidates: list,

) -> list[SeriesVote]:

    """Build series votes from winning-cluster members in a title/author breakdown."""

    if not score_breakdown or score_breakdown.get("status") == "no_match":

        return []



    winning_cluster_id: int | None = None

    pool = score_breakdown.get("evidence_pool") or []

    rep = score_breakdown.get("representative") or {}

    for entry in pool:

        if (

            entry.get("source") == rep.get("source")

            and entry.get("author") == rep.get("author")

            and entry.get("title") == rep.get("title")

        ):

            winning_cluster_id = entry.get("cluster_id")

            break

    if winning_cluster_id is None:

        return []



    cand_by_key: dict[tuple[str, str, str], object] = {}

    for cand in candidates:

        key = (cand.source, cand.author, cand.title)

        cand_by_key.setdefault(key, cand)



    votes: list[SeriesVote] = []

    seen_families: set[str] = set()

    for entry in pool:

        if entry.get("cluster_id") != winning_cluster_id:

            continue

        source = entry.get("source") or ""

        family = series_family(source)

        if not family or family in seen_families:

            continue

        cand = cand_by_key.get(

            (source, entry.get("author") or "", entry.get("title") or "")

        )

        if cand is None:

            continue

        series = (getattr(cand, "series", "") or "").strip()

        series_index = (getattr(cand, "series_index", "") or "").strip()

        if not series:

            continue

        seen_families.add(family)

        votes.append(

            SeriesVote(

                family=family,

                series=series,

                series_index=series_index,

            )

        )

    return votes





def id3_series_vote(tags) -> SeriesVote | None:

    """Extract a series vote from ID3 contentgroup/grouping tags."""

    raw = getattr(tags, "raw", None) or {}

    series = raw.get("contentgroup") or raw.get("grouping") or ""

    if isinstance(series, (list, tuple)):

        series = str(series[0]) if series else ""

    series = str(series).strip()

    if not series:

        return None

    return SeriesVote(family="id3_series", series=series, series_index="")





def annotate_series_membership(candidates: list, series_breakdown: dict) -> None:
    """Set ``series_membership`` on each candidate from winning series cluster support."""
    families: dict[str, float] = {}
    for family, support in (series_breakdown.get("families") or {}).items():
        if family:
            families[family] = float(support or 0.0)

    caps = series_breakdown.get("caps_applied") or []
    if "single_source_series_cap" in caps:
        family_membership: dict[str, float] = {}
        for family, support in families.items():
            if support > 0:
                family_membership[family] = min(support, SINGLE_SOURCE_SERIES_CAP)
    else:
        family_membership = families

    for cand in candidates:
        family = series_family(getattr(cand, "source", "") or "")
        if not family:
            cand.series_membership = 0.0
            continue
        cand.series_membership = family_membership.get(family, 0.0)


# Back-compat alias

series_votes_from_breakdown = pick_series_votes_from_cluster


