from __future__ import annotations

from pathlib import Path

from stager_core.metadata.audible import AUDIBLE_RESPONSE_GROUPS, AudibleProvider
from stager_core.metadata.audnexus import AudnexusProvider
from stager_core.metadata.cache import ApiCache
from stager_core.metadata.google_books import GoogleBooksProvider
from stager_core.metadata.mam import (
    MAM_SEARCH_URL,
    MamProvider,
    extract_mam_id_from_headers,
    mam_search_body,
    persist_stager_mam_cookie,
    resolve_mam_id,
    resolve_stager_mam_id,
    stager_mam_cookie_path,
)
from stager_core.metadata.openlibrary import OpenLibraryProvider
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

__all__ = [
    "AUDIBLE_RESPONSE_GROUPS",
    "MAM_SEARCH_URL",
    "MetadataProviders",
    "extract_mam_id_from_headers",
    "mam_search_body",
    "persist_stager_mam_cookie",
    "resolve_mam_id",
    "resolve_stager_mam_id",
    "stager_mam_cookie_path",
]


class MetadataProviders:
    """Live provider facade. Each catalog lives in its own module and calls RateLimitedClient."""

    def __init__(
        self,
        client: RateLimitedClient,
        cache: ApiCache,
        *,
        region: str = "us",
        google_api_key: str = "",
        mam_id: str = "",
        mam_cookie_path: Path | str | None = None,
    ):
        self.client = client
        self.cache = cache
        self._audnexus = AudnexusProvider(client, cache, region=region)
        self._audible = AudibleProvider(client, cache, audnexus=self._audnexus)
        self._openlibrary = OpenLibraryProvider(client, cache)
        self._google = GoogleBooksProvider(client, cache, google_api_key=google_api_key)
        self._mam = MamProvider(client, cache, mam_id=mam_id, mam_cookie_path=mam_cookie_path)

    @property
    def region(self) -> str:
        return self._audnexus.region

    @region.setter
    def region(self, value: str) -> None:
        self._audnexus.region = value

    @property
    def google_api_key(self) -> str:
        return self._google.google_api_key

    @google_api_key.setter
    def google_api_key(self, value: str) -> None:
        self._google.google_api_key = (value or "").strip()

    @property
    def mam_id(self) -> str:
        return self._mam.mam_id

    @mam_id.setter
    def mam_id(self, value: str) -> None:
        self._mam.mam_id = (value or "").strip()

    @property
    def mam_cookie_path(self) -> Path | None:
        return self._mam.mam_cookie_path

    def audnexus_book(self, asin: str) -> list[MetadataCandidate]:
        return self._audnexus.audnexus_book(asin)

    def audible_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        return self._audible.audible_search(title, author)

    def audible_author_catalog(
        self,
        author: str = "",
        *,
        num_results: int = 10,
    ) -> list[MetadataCandidate]:
        return self._audible.audible_author_catalog(author, num_results=num_results)

    def mam_search(
        self,
        title: str = "",
        author: str = "",
        *,
        perpage: int = 5,
    ) -> list[MetadataCandidate]:
        return self._mam.mam_search(title, author, perpage=perpage)

    def openlibrary_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        return self._openlibrary.openlibrary_search(title, author)

    def google_books_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        return self._google.google_books_search(title, author)

    def audible_search_title_only(self, title: str) -> list[MetadataCandidate]:
        return self._audible.audible_search_title_only(title)

    def mam_search_title_only(self, title: str, *, perpage: int = 5) -> list[MetadataCandidate]:
        return self._mam.mam_search_title_only(title, perpage=perpage)

    def openlibrary_search_title_only(self, title: str) -> list[MetadataCandidate]:
        return self._openlibrary.openlibrary_search_title_only(title)

    def google_books_search_title_only(self, title: str) -> list[MetadataCandidate]:
        return self._google.google_books_search_title_only(title)

    def audnexus_author_verify(self, author_name: str) -> MetadataCandidate | None:
        return self._audnexus.audnexus_author_verify(author_name)

    def probe_connectivity(self, provider_id: str) -> tuple[str | int, str]:
        """Return (status, message) where status is 'ok', 'skipped', or HTTP code."""
        if provider_id == "audnexus":
            return self._audnexus.probe()
        if provider_id == "audible":
            return self._audible.probe()
        if provider_id == "openlibrary":
            return self._openlibrary.probe()
        if provider_id == "google_books":
            return self._google.probe()
        if provider_id == "mam":
            return self._mam.probe()
        return 0, "unknown provider"
