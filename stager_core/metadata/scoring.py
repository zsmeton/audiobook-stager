"""Weighted cross-source agreement scorer (bounded noisy-OR).

Confidence is computed as a bounded noisy-OR over the *source families* that
corroborate the winning cluster, so it lives in ``[0, 1]`` by construction and
rises only as independent reputable sources agree. There is no fixed authority:
sources contribute according to a single named prior table and graded,
two-threshold cluster membership.

All judgment-based knobs live in the CONFIG block below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from stager_core.metadata.normalize import (
    is_publisher_name,
    normalize_author,
    normalize_title,
)

# ============================== CONFIG (tunables) ==============================
SAME_BOOK_THRESHOLD = 0.88
POSSIBLE_BOOK_THRESHOLD = 0.75
WEAK_SUPPORT_FLOOR = 0.5
AUTO_STAGE_GATE = 0.90  # informational; the app owns the actual gate

TITLE_WEIGHT = 0.65
AUTHOR_WEIGHT = 0.35

# Source-family reliability priors. MAM is favored per design. Local evidence
# splits into TWO independent families: ``tags`` (id3 embedded metadata) and
# ``path`` (folder + filename on-disk naming, collapsed by max within the
# family). When tags and path agree they corroborate; when they disagree they
# fall into different clusters.
FAMILY_PRIORS: dict[str, float] = {
    "mam_exact": 0.95,  # Phase 2 (exact infohash match)
    "mam": 0.85,
    "author_oeuvre": 0.85,  # Audible+MAM author catalog, locally disambiguated
    "title_first": 0.75,  # explicit title-only provider search, first hit per provider
    "audible": 0.80,
    "audnexus": 0.80,
    "google_books": 0.70,
    "openlibrary": 0.60,
    "tags": 0.65,
    "path": 0.65,
    "library": 0.80,
}
TAGS_FAMILY = "tags"
PATH_FAMILY = "path"
TAGS_SOURCES = frozenset({"id3"})
PATH_SOURCES = frozenset({"folder", "filename"})
LOCAL_FAMILIES = frozenset({TAGS_FAMILY, PATH_FAMILY})

# Caps applied AFTER the noisy-OR.
MAM_EXACT_FLOOR = 0.95
LOCAL_ONLY_CAP = 0.65
MISSING_AUTHOR_CAP = 0.70
AMBIGUOUS_CAP = 0.55
AMBIGUITY_MARGIN = 0.15
# ==============================================================================

_CHAPTER_TITLE_RE = re.compile(
    r"^(?:chapter|ch\.?|track|disc|disk|cd|part|pt\.?|intro(?:duction)?|"
    r"prologue|epilogue|opening\s+credits|end\s+credits)\b\s*#?\d*\s*$",
    re.IGNORECASE,
)
_ANCILLARY_TITLE_RE = re.compile(
    r"\b(workbook|study guide|summary|companion)\b",
    re.IGNORECASE,
)
_BUNDLE_TITLE_RE = re.compile(r"&\s*the\s+.*workbook", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Evidence:
    source: str
    author: str
    title: str
    weight: float = 1.0
    extras: dict = field(default_factory=dict)


# ------------------------------------------------------------------ family/prior
def source_family(source: str) -> str:
    if source in TAGS_SOURCES:
        return TAGS_FAMILY
    if source in PATH_SOURCES:
        return PATH_FAMILY
    return source


def source_prior(source: str) -> float:
    return FAMILY_PRIORS.get(source_family(source), 0.0)


# ----------------------------------------------------------------------- matchers
def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def token_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def sequence_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def containment(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def title_sim(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return max(token_overlap(na, nb), sequence_ratio(na, nb), containment(na, nb))


def _canon_author(author: str) -> str:
    a = normalize_author(author)
    if "," in a:
        last, _, first = a.partition(",")
        a = f"{first.strip()} {last.strip()}".strip()
    return a


def author_sim(a: str, b: str) -> float:
    ca, cb = _canon_author(a), _canon_author(b)
    if not ca or not cb:
        return 0.0
    base = max(token_overlap(ca, cb), sequence_ratio(ca, cb), containment(ca, cb))
    # Surname agreement is a strong signal even when given names differ/abbrev.
    sa = ca.split()[-1] if ca.split() else ""
    sb = cb.split()[-1] if cb.split() else ""
    if sa and sa == sb:
        base = max(base, 0.85)
    return base


def pair_sim(e1: Evidence, e2: Evidence) -> float:
    t_sim = title_sim(e1.title, e2.title)
    if not e1.author or not e2.author:
        # Cannot compare authors; fall back to title agreement only.
        return t_sim
    a_sim = author_sim(e1.author, e2.author)
    return AUTHOR_WEIGHT * a_sim + TITLE_WEIGHT * t_sim


def membership_grade(sim: float) -> float:
    if sim >= SAME_BOOK_THRESHOLD:
        return 1.0
    if sim >= POSSIBLE_BOOK_THRESHOLD:
        span = SAME_BOOK_THRESHOLD - POSSIBLE_BOOK_THRESHOLD
        return WEAK_SUPPORT_FLOOR + 0.5 * (sim - POSSIBLE_BOOK_THRESHOLD) / span
    return 0.0


# --------------------------------------------------------------------- filtering
def _is_ancillary_title(title: str) -> bool:
    if not title:
        return False
    return bool(_ANCILLARY_TITLE_RE.search(title) or _BUNDLE_TITLE_RE.search(title))


def _can_join_cluster(ev: Evidence, cluster: _Cluster, sim: float) -> bool:
    rep = cluster.representative
    ev_anc = _is_ancillary_title(ev.title)
    rep_anc = _is_ancillary_title(rep.title)
    if ev_anc or rep_anc:
        if ev_anc != rep_anc:
            return False
        return sim >= SAME_BOOK_THRESHOLD
    return sim >= POSSIBLE_BOOK_THRESHOLD


def _is_droppable(ev: Evidence) -> bool:
    title = (ev.title or "").strip()
    if not title:
        return True
    if _CHAPTER_TITLE_RE.match(title):
        return True
    # Publisher-as-author with no real title signal is not a usable vote.
    if is_publisher_name(ev.author) and not normalize_title(title):
        return True
    return False


# ---------------------------------------------------------------------- clustering
@dataclass
class _Member:
    ev: Evidence
    membership: float


@dataclass
class _Cluster:
    members: list[_Member]

    @property
    def representative(self) -> Evidence:
        return self.members[0].ev


def _mean_pair_sim(member: _Member, members: list[_Member]) -> float:
    others = [m for m in members if m is not member]
    if not others:
        return 1.0
    return sum(pair_sim(member.ev, other.ev) for other in others) / len(others)


def _pick_representative(cluster: _Cluster) -> Evidence:
    """Medoid: member with highest mean similarity to all siblings."""
    members = cluster.members
    if len(members) == 1:
        return members[0].ev
    best = members[0]
    best_key = (-1.0, -1.0, len(best.ev.title or ""))
    for member in members:
        key = (
            _mean_pair_sim(member, members),
            member.membership,
            -len(member.ev.title or ""),
        )
        if key > best_key:
            best_key = key
            best = member
    return best.ev


def _cluster(evidence: list[Evidence]) -> list[_Cluster]:
    # Highest prior seeds first; ties keep input order (stable sort).
    ordered = sorted(evidence, key=lambda e: source_prior(e.source), reverse=True)
    clusters: list[_Cluster] = []
    for ev in ordered:
        best_cluster: _Cluster | None = None
        best_sim = 0.0
        for cluster in clusters:
            sim = pair_sim(cluster.representative, ev)
            if _can_join_cluster(ev, cluster, sim) and sim > best_sim:
                best_sim = sim
                best_cluster = cluster
        if best_cluster is not None:
            best_cluster.members.append(_Member(ev, membership_grade(best_sim)))
        else:
            clusters.append(_Cluster(members=[_Member(ev, 1.0)]))
    return clusters


def _family_support(cluster: _Cluster) -> dict[str, dict]:
    """Best ``prior * membership`` vote per source family in the cluster."""
    families: dict[str, dict] = {}
    for member in cluster.members:
        fam = source_family(member.ev.source)
        prior = source_prior(member.ev.source)
        support = prior * member.membership
        current = families.get(fam)
        if current is None or support > current["support"]:
            families[fam] = {
                "prior": round(prior, 4),
                "membership": round(member.membership, 4),
                "support": support,
                "best_source": member.ev.source,
            }
    for fam in families.values():
        fam["support"] = round(fam["support"], 4)
    return families


def _noisy_or(families: dict[str, dict]) -> float:
    product = 1.0
    for fam in families.values():
        product *= 1.0 - fam["support"]
    return 1.0 - product


def _cluster_confidence(cluster: _Cluster) -> tuple[float, dict[str, dict]]:
    families = _family_support(cluster)
    return _noisy_or(families), families


def _apply_cluster_caps(
    raw_conf: float,
    cluster: _Cluster,
    families: dict[str, dict],
    *,
    apply_ambiguous: bool = False,
    runner_up_raw: float | None = None,
) -> tuple[float, list[str]]:
    """Return capped cluster confidence and cap labels applied."""
    caps_applied: list[str] = []
    conf = raw_conf
    rep = _pick_representative(cluster)

    has_external = any(fam not in LOCAL_FAMILIES for fam in families)
    if not has_external:
        conf = min(conf, LOCAL_ONLY_CAP)
        caps_applied.append(f"local_only_cap:{LOCAL_ONLY_CAP}")
    if not normalize_author(rep.author):
        conf = min(conf, MISSING_AUTHOR_CAP)
        caps_applied.append(f"missing_author_cap:{MISSING_AUTHOR_CAP}")
    if (
        apply_ambiguous
        and runner_up_raw is not None
        and (raw_conf - runner_up_raw) <= AMBIGUITY_MARGIN
    ):
        conf = min(conf, AMBIGUOUS_CAP)
        caps_applied.append(f"ambiguous_cap:{AMBIGUOUS_CAP}")
    if "mam_exact" in families:
        conf = max(conf, MAM_EXACT_FLOOR)
        caps_applied.append(f"mam_exact_floor:{MAM_EXACT_FLOOR}")

    return round(max(0.0, min(1.0, conf)), 4), caps_applied


# ------------------------------------------------------------------------- public
def pick_winner(evidence_list: list[Evidence]) -> tuple[object, dict]:
    """Return ``(winner_candidate, score_breakdown)``.

    ``winner_candidate`` is the representative evidence's attached candidate
    (``extras["candidate"]``) with ``confidence``/``score_breakdown`` set, or
    ``None`` when there is no usable evidence.
    """
    usable = [ev for ev in evidence_list if not _is_droppable(ev)]
    if not usable:
        return None, {
            "status": "no_match",
            "confidence": 0.0,
            "raw_confidence": 0.0,
            "cluster_size": 0,
            "families": {},
            "evidence_pool": [],
        }

    clusters = _cluster(usable)
    cluster_raw: list[tuple[float, dict[str, dict]]] = [
        _cluster_confidence(cluster) for cluster in clusters
    ]
    scored = sorted(
        enumerate(clusters),
        key=lambda item: (
            cluster_raw[item[0]][0],
            len(item[1].members),
            source_prior(item[1].representative.source),
        ),
        reverse=True,
    )

    winner_id, winner_cluster = scored[0]
    winner_raw, winner_families = cluster_raw[winner_id]
    runner_up = scored[1] if len(scored) > 1 else None
    runner_up_raw = cluster_raw[runner_up[0]][0] if runner_up is not None else None

    cluster_confidences: dict[int, float] = {}
    for cluster_id, cluster in enumerate(clusters):
        raw_conf, families = cluster_raw[cluster_id]
        is_winner = cluster_id == winner_id
        capped, _ = _apply_cluster_caps(
            raw_conf,
            cluster,
            families,
            apply_ambiguous=is_winner,
            runner_up_raw=runner_up_raw if is_winner else None,
        )
        cluster_confidences[cluster_id] = capped

    winner_conf, caps_applied = _apply_cluster_caps(
        winner_raw,
        winner_cluster,
        winner_families,
        apply_ambiguous=True,
        runner_up_raw=runner_up_raw,
    )
    status = "ambiguous" if any(c.startswith("ambiguous_cap:") for c in caps_applied) else "ok"
    rep = _pick_representative(winner_cluster)

    evidence_pool = [
        {
            "source": member.ev.source,
            "author": member.ev.author,
            "title": member.ev.title,
            "cluster_id": cluster_id,
            "membership": round(member.membership, 4),
            "medoid_score": round(_mean_pair_sim(member, cluster.members), 4),
            "cluster_confidence": cluster_confidences[cluster_id],
        }
        for cluster_id, cluster in enumerate(clusters)
        for member in cluster.members
    ]

    runner_up_info = None
    if runner_up is not None:
        ru_id, ru_cluster = runner_up
        ru_rep = _pick_representative(ru_cluster)
        runner_up_info = {
            "confidence": cluster_confidences[ru_id],
            "size": len(ru_cluster.members),
            "source": ru_rep.source,
            "author": ru_rep.author,
            "title": ru_rep.title,
        }

    breakdown = {
        "status": status,
        "confidence": winner_conf,
        "raw_confidence": round(winner_raw, 4),
        "cluster_size": len(winner_cluster.members),
        "cluster_confidences": cluster_confidences,
        "representative": {
            "source": rep.source,
            "author": rep.author,
            "title": rep.title,
        },
        "families": {
            fam: {
                "prior": data["prior"],
                "membership": data["membership"],
                "support": data["support"],
                "best_source": data["best_source"],
            }
            for fam, data in winner_families.items()
        },
        "members": [
            {
                "source": m.ev.source,
                "author": m.ev.author,
                "title": m.ev.title,
                "membership": round(m.membership, 4),
                "medoid_score": round(_mean_pair_sim(m, winner_cluster.members), 4),
                "cluster_confidence": winner_conf,
            }
            for m in winner_cluster.members
        ],
        "caps_applied": caps_applied,
        "ambiguity_margin": AMBIGUITY_MARGIN,
        "runner_up": runner_up_info,
        "evidence_pool": evidence_pool,
    }

    candidate = rep.extras.get("candidate")
    if candidate is not None:
        candidate.confidence = winner_conf
        candidate.score_breakdown = breakdown
    return candidate, breakdown
