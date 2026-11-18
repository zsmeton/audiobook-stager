from __future__ import annotations

import json
import urllib.parse

from stager_core.metadata.cache import ApiCache
from stager_core.metadata.normalize import normalize_author, normalize_title, provider_text
from stager_core.metadata.provider_registry import empty_key_blocks
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

_PROBE_TITLE = "Red Rising"
_PROBE_AUTHOR = "Pierce Brown"


def _clean_title(title: str) -> str:
    return normalize_title(provider_text(title or ""))


def _clean_author(author: str) -> str:
    return normalize_author(provider_text(author or ""))


class GoogleBooksProvider:
    def __init__(self, client: RateLimitedClient, cache: ApiCache, *, google_api_key: str = ""):
        self.client = client
        self.cache = cache
        self.google_api_key = google_api_key.strip()

    def google_books_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        if empty_key_blocks("google_books", self.google_api_key):
            return []
        title = (title or "").strip()
        author = (author or "").strip()
        # Build the query from whichever fields are present (intitle/inauthor).
        q_parts = []
        if title:
            q_parts.append(f"intitle:{title}")
        if author:
            q_parts.append(f"inauthor:{author}")
        if not q_parts:
            return []
        query = "+".join(urllib.parse.quote(p) for p in q_parts)
        cache_key = f"search:{query}"
        cached = self.cache.get("google_books", cache_key)
        if cached:
            status, body = cached
            if status == 200:
                return self._candidates_from_google(body)
            return []

        url = (
            "https://www.googleapis.com/books/v1/volumes?"
            + urllib.parse.urlencode({"q": " ".join(q_parts), "maxResults": 3, "key": self.google_api_key})
        )
        status, payload, _headers = self.client.request_json("google_books", url)
        if status == 200 and isinstance(payload, dict):
            self.cache.put_permanent("google_books", cache_key, status, payload)
            return self._candidates_from_google(payload)
        if status == 429:
            self.cache.put("google_books", cache_key, status, "{}", ttl_seconds=3600)
        return []

    def _candidates_from_google(self, payload: dict | str) -> list[MetadataCandidate]:
        if isinstance(payload, str):
            payload = json.loads(payload)
        candidates: list[MetadataCandidate] = []
        for item in payload.get("items") or []:
            info = item.get("volumeInfo") or {}
            title = info.get("title") or ""
            subtitle = info.get("subtitle") or ""
            authors = info.get("authors") or []
            author = authors[0] if authors else ""
            published = str(info.get("publishedDate") or "")
            identifiers = info.get("industryIdentifiers") or []
            isbn = ""
            for ident in identifiers:
                if ident.get("type") in {"ISBN_13", "ISBN_10"}:
                    isbn = str(ident.get("identifier", "") or "")
                    if ident.get("type") == "ISBN_13":
                        break
            images = info.get("imageLinks") or {}
            candidates.append(
                MetadataCandidate(
                    author=_clean_author(author) or "Unknown Author",
                    title=_clean_title(title) or title,
                    source="google_books",
                    confidence=0.0,
                    subtitle=subtitle,
                    isbn=isbn,
                    language=str(info.get("language", "") or ""),
                    publisher=str(info.get("publisher", "") or ""),
                    year=published[:4] if published else "",
                    description=str(info.get("description", "") or ""),
                    cover_url=str(images.get("thumbnail", "") or ""),
                    raw=info,
                )
            )
        return candidates

    def google_books_search_title_only(self, title: str) -> list[MetadataCandidate]:
        """Explicit title-only Google Books search; inauthor omitted from query."""
        return self.google_books_search((title or "").strip(), "")

    def probe(self) -> tuple[str | int, str]:
        if empty_key_blocks("google_books", self.google_api_key):
            return "skipped", "API key not configured"
        q = f"intitle:{_PROBE_TITLE}+inauthor:{_PROBE_AUTHOR}"
        url = (
            "https://www.googleapis.com/books/v1/volumes?"
            + urllib.parse.urlencode({"q": q, "maxResults": 1, "key": self.google_api_key})
        )
        status, _payload, _headers = self.client.request_json("google_books", url)
        if status == 200:
            return "ok", "OK"
        return status, f"HTTP {status}"
