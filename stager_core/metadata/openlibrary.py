from __future__ import annotations

import json
import urllib.parse

from stager_core.metadata.cache import ApiCache
from stager_core.metadata.normalize import normalize_author, normalize_title, provider_text
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

_PROBE_TITLE = "Red Rising"
_PROBE_AUTHOR = "Pierce Brown"


def _clean_title(title: str) -> str:
    return normalize_title(provider_text(title or ""))


def _clean_author(author: str) -> str:
    return normalize_author(provider_text(author or ""))


class OpenLibraryProvider:
    """Keyless catalog search. A blank contact email does not disable this provider."""

    def __init__(self, client: RateLimitedClient, cache: ApiCache):
        self.client = client
        self.cache = cache

    def openlibrary_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        # Supports title-only, author-only, or combined; only present fields are
        # sent as query params (OpenLibrary handles an author-only search).
        title = (title or "").strip()
        author = (author or "").strip()
        if not title and not author:
            return []
        params = {
            "limit": "3",
            "fields": "key,title,author_name,first_publish_year,isbn,language,cover_i",
        }
        if title:
            params["title"] = title
        if author:
            params["author"] = author
        cache_key = "search:" + urllib.parse.urlencode(sorted(params.items()))
        cached = self.cache.get("openlibrary", cache_key)
        if cached:
            status, body = cached
            if status == 200:
                return self._candidates_from_openlibrary(body)
            return []

        url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(params)
        status, payload, _headers = self.client.request_json("openlibrary", url)
        if status == 200 and isinstance(payload, dict):
            self.cache.put_permanent("openlibrary", cache_key, status, payload)
            return self._candidates_from_openlibrary(payload)
        if status == 429:
            self.cache.put("openlibrary", cache_key, status, "{}", ttl_seconds=60)
        elif status == 404:
            self.cache.put("openlibrary", cache_key, status, "{}", ttl_seconds=7 * 86400)
        return []

    def _candidates_from_openlibrary(self, payload: dict | str) -> list[MetadataCandidate]:
        if isinstance(payload, str):
            payload = json.loads(payload)
        candidates: list[MetadataCandidate] = []
        for doc in payload.get("docs") or []:
            title = doc.get("title") or ""
            authors = doc.get("author_name") or []
            author = authors[0] if authors else ""
            isbns = doc.get("isbn") or []
            langs = doc.get("language") or []
            cover_i = doc.get("cover_i")
            candidates.append(
                MetadataCandidate(
                    author=_clean_author(author) or "Unknown Author",
                    title=_clean_title(title) or title,
                    source="openlibrary",
                    confidence=0.0,
                    isbn=str(isbns[0]) if isbns else "",
                    language=str(langs[0]) if langs else "",
                    year=str(doc.get("first_publish_year") or ""),
                    cover_url=(
                        f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
                        if cover_i
                        else ""
                    ),
                    raw=doc,
                )
            )
        return candidates

    def openlibrary_search_title_only(self, title: str) -> list[MetadataCandidate]:
        """Explicit title-only Open Library search; author param omitted."""
        return self.openlibrary_search((title or "").strip(), "")

    def probe(self) -> tuple[str | int, str]:
        url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(
            {"title": _PROBE_TITLE, "author": _PROBE_AUTHOR, "limit": "1"}
        )
        status, _payload, _headers = self.client.request_json("openlibrary", url)
        if status == 200:
            return "ok", "OK"
        return status, f"HTTP {status}"
