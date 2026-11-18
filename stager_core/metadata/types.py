from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ManualHints:
    author: str = ""
    title: str = ""
    series: str = ""
    series_index: str = ""


@dataclass
class TagInfo:
    title: str = ""
    album: str = ""
    artist: str = ""
    albumartist: str = ""
    asin: str = ""
    narrator: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetadataCandidate:
    author: str
    title: str
    source: str
    confidence: float
    # Enriched, optional metadata. Providers populate what they have; persisted
    # via candidates_json so a future filler app can emit metadata.json without
    # re-fetching. No new DB columns are introduced.
    narrator: str = ""
    series: str = ""
    series_index: str = ""
    subtitle: str = ""
    asin: str = ""
    isbn: str = ""
    language: str = ""
    publisher: str = ""
    year: str = ""
    description: str = ""
    cover_url: str = ""
    # Cluster annotation populated by the scorer via annotate_candidates().
    cluster_id: int = -1
    cluster_confidence: float = 0.0
    cluster_membership: float = 0.0
    in_winning_cluster: bool = False
    medoid_score: float = 0.0
    medoid_rank: int = 0
    series_membership: float = 0.0
    lvi_author_match: float = 0.0
    lvi_series_match: float = 0.0
    lvi_author_matched: bool = False
    lvi_series_matched: bool = False
    lvi_in_library: bool = False
    # Explainable scoring breakdown, only populated on the winning candidate.
    score_breakdown: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
