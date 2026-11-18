from __future__ import annotations

import json
import urllib.parse

from stager_core.metadata.cache import ApiCache
from stager_core.metadata.normalize import normalize_author, normalize_title, provider_text
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

_PROBE_ASIN = "B00I2VWW5U"


def _overlap_score(query: str, candidate: str) -> float:
    q = {t.lower() for t in query.replace("-", " ").split() if len(t) > 2}
    c = {t.lower() for t in candidate.replace("-", " ").split() if len(t) > 2}
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


def _clean_title(title: str) -> str:
    return normalize_title(provider_text(title or ""))


def _clean_author(author: str) -> str:
    return normalize_author(provider_text(author or ""))


class AudnexusProvider:
    def __init__(self, client: RateLimitedClient, cache: ApiCache, *, region: str = "us"):
        self.client = client
        self.cache = cache
        self.region = region

    def audnexus_book(self, asin: str) -> list[MetadataCandidate]:
        asin = asin.upper()
        cache_key = f"book:{asin}:{self.region}"
        cached = self.cache.get("audnexus", cache_key)
        if cached:
            status, body = cached
            if status == 200:
                return self._candidates_from_audnexus_book(body)
            return []

        url = f"https://api.audnex.us/books/{urllib.parse.quote(asin)}?region={self.region}"
        status, payload, _headers = self.client.request_json("audnexus", url)
        if status == 200 and isinstance(payload, dict):
            self.cache.put_permanent("audnexus", cache_key, status, payload)
            return self._candidates_from_audnexus_book(payload)
        if status == 429:
            self.cache.put("audnexus", cache_key, status, "{}", ttl_seconds=60)
        elif status == 404 and payload is not None:
            self.cache.put("audnexus", cache_key, status, json.dumps(payload), ttl_seconds=7 * 86400)
        return []

    def _candidates_from_audnexus_book(self, payload: dict | str) -> list[MetadataCandidate]:
        if isinstance(payload, str):
            payload = json.loads(payload)
        authors = payload.get("authors") or []
        author = ", ".join(a.get("name", "") for a in authors if a.get("name"))
        title = payload.get("title") or ""
        subtitle = payload.get("subtitle") or ""
        narrators = payload.get("narrators") or []
        narrator = ", ".join(n.get("name", "") for n in narrators if n.get("name"))
        series_primary = payload.get("seriesPrimary") or {}
        release = str(payload.get("releaseDate") or "")
        return [
            MetadataCandidate(
                author=_clean_author(author) or "Unknown Author",
                title=_clean_title(title) or "Untitled",
                source="audnexus",
                confidence=0.0,
                narrator=narrator,
                series=series_primary.get("name", "") or "",
                series_index=str(series_primary.get("position", "") or ""),
                subtitle=subtitle,
                asin=str(payload.get("asin", "") or ""),
                isbn=str(payload.get("isbn", "") or ""),
                language=str(payload.get("language", "") or ""),
                publisher=str(payload.get("publisherName", "") or ""),
                year=release[:4] if release else "",
                description=str(payload.get("summary") or payload.get("description") or ""),
                cover_url=str(payload.get("image", "") or ""),
                raw=payload,
            )
        ]

    def audnexus_author_verify(self, author_name: str) -> MetadataCandidate | None:
        cache_key = f"author:{author_name}:{self.region}"
        cached = self.cache.get("audnexus", cache_key)
        if cached:
            status, body = cached
            if status == 200:
                return self._best_author_match(body, author_name)
            return None

        url = "https://api.audnex.us/authors?" + urllib.parse.urlencode(
            {"name": author_name, "region": self.region}
        )
        status, payload, _headers = self.client.request_json("audnexus", url)
        if status == 200 and isinstance(payload, list):
            self.cache.put_permanent("audnexus", cache_key, status, {"results": payload})
            return self._best_author_match({"results": payload}, author_name)
        return None

    def _best_author_match(self, payload: dict | str, query: str) -> MetadataCandidate | None:
        if isinstance(payload, str):
            payload = json.loads(payload)
        results = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(results, list) or not results:
            return None
        best = None
        best_score = -1.0
        for item in results:
            name = item.get("name") or ""
            score = _overlap_score(query, name)
            if score > best_score:
                best_score = score
                best = item
        if not best:
            return None
        return MetadataCandidate(
            author=best.get("name") or query,
            title="",
            source="audnexus_author",
            confidence=0.0,
            raw=best,
        )

    def probe(self) -> tuple[str | int, str]:
        url = f"https://api.audnex.us/books/{_PROBE_ASIN}?region={self.region}"
        status, _payload, _headers = self.client.request_json("audnexus", url)
        if status == 200:
            return "ok", "OK"
        return status, f"HTTP {status}"
