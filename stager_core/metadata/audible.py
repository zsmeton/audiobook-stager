from __future__ import annotations

import json
import urllib.parse

from stager_core.metadata.audnexus import AudnexusProvider
from stager_core.metadata.cache import ApiCache
from stager_core.metadata.normalize import normalize_author, normalize_title, provider_text
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

AUDIBLE_RESPONSE_GROUPS = "product_desc,product_attrs,contributors,series,media,product_extended_attrs"
_PROBE_TITLE = "Red Rising"
_PROBE_AUTHOR = "Pierce Brown"


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


class AudibleProvider:
    def __init__(
        self,
        client: RateLimitedClient,
        cache: ApiCache,
        *,
        audnexus: AudnexusProvider,
    ):
        self.client = client
        self.cache = cache
        self._audnexus = audnexus

    def audible_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        # Accepts combined (title+author), title-only, or author-only queries.
        # Only the present field(s) are sent so distinct passes cache apart.
        title = (title or "").strip()
        author = (author or "").strip()
        if not title and not author:
            return []
        params = {
            "num_results": "3",
            "products_sort_by": "Relevance",
            "response_groups": AUDIBLE_RESPONSE_GROUPS,
        }
        if title:
            params["title"] = title
        if author:
            params["author"] = author
        cache_key = "search:" + urllib.parse.urlencode(sorted(params.items()))
        cached = self.cache.get("audible", cache_key)
        if cached:
            status, body = cached
            payload = json.loads(body) if (status == 200 and body) else None
        else:
            url = "https://api.audible.com/1.0/catalog/products?" + urllib.parse.urlencode(params)
            status, payload, _headers = self.client.request_json("audible", url)
            if status == 200 and isinstance(payload, dict):
                self.cache.put_permanent("audible", cache_key, status, payload)
            elif status == 429:
                self.cache.put("audible", cache_key, status, "{}", ttl_seconds=300)

        asin = self._best_audible_asin(payload, title, author)
        if not asin:
            return []
        product = self._audible_product_for_asin(payload, asin)
        audnexus_hits = self._audnexus.audnexus_book(asin)
        if audnexus_hits:
            return [self._audible_candidate_from_audnexus(audnexus_hits[0], asin)]
        if not product:
            return []
        return [self._candidate_from_audible_product(product, asin, fallback_title=title)]

    def audible_author_catalog(
        self,
        author: str = "",
        *,
        num_results: int = 10,
    ) -> list[MetadataCandidate]:
        """Return all Audible products for an author-only query."""
        author = (author or "").strip()
        if not author:
            return []
        params = {
            "num_results": str(num_results),
            "products_sort_by": "Relevance",
            "response_groups": AUDIBLE_RESPONSE_GROUPS,
            "author": author,
        }
        cache_key = "search:" + urllib.parse.urlencode(sorted(params.items()))
        cached = self.cache.get("audible", cache_key)
        if cached:
            status, body = cached
            payload = json.loads(body) if (status == 200 and body) else None
        else:
            url = "https://api.audible.com/1.0/catalog/products?" + urllib.parse.urlencode(params)
            status, payload, _headers = self.client.request_json("audible", url)
            if status == 200 and isinstance(payload, dict):
                self.cache.put_permanent("audible", cache_key, status, payload)
            elif status == 429:
                self.cache.put("audible", cache_key, status, "{}", ttl_seconds=300)

        out: list[MetadataCandidate] = []
        for product in self._audible_products(payload):
            asin = str(product.get("asin", "") or "")
            if not asin:
                continue
            out.append(
                self._candidate_from_audible_product(product, asin, fallback_title="")
            )
        return out

    def audible_search_title_only(self, title: str) -> list[MetadataCandidate]:
        """Explicit title-only Audible search; author param omitted from API request."""
        return self.audible_search((title or "").strip(), "")

    @staticmethod
    def _audible_products(payload: dict | None) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        products = payload.get("products")
        return products if isinstance(products, list) else []

    def _best_audible_asin(self, payload: dict | None, title: str, author: str) -> str:
        products = self._audible_products(payload)
        if not products:
            return ""
        best_asin = ""
        best_score = -1.0
        for product in products:
            asin = str(product.get("asin", "") or "")
            if not asin:
                continue
            p_title = product.get("title") or ""
            score = _overlap_score(title, p_title)
            if author:
                authors = product.get("authors") or []
                a_name = " ".join(a.get("name", "") for a in authors)
                score += _overlap_score(author, a_name) * 0.5
            if score > best_score:
                best_score = score
                best_asin = asin
        # Fall back to the first (Relevance-sorted) product if scoring is flat.
        if not best_asin and products:
            best_asin = str(products[0].get("asin", "") or "")
        return best_asin

    def _parse_audible_series(self, product: dict) -> tuple[str, str]:
        series_list = product.get("series") or []
        if not isinstance(series_list, list) or not series_list:
            return "", ""
        entry = series_list[0] if isinstance(series_list[0], dict) else {}
        name = str(entry.get("title") or entry.get("name") or "").strip()
        index = str(entry.get("sequence") or entry.get("position") or "").strip()
        return name, index

    def _candidate_from_audible_product(
        self,
        product: dict,
        asin: str,
        *,
        fallback_title: str = "",
    ) -> MetadataCandidate:
        authors = product.get("authors") or []
        author_name = ", ".join(a.get("name", "") for a in authors if a.get("name"))
        series_name, series_index = self._parse_audible_series(product)
        return MetadataCandidate(
            author=_clean_author(author_name) or "Unknown Author",
            title=_clean_title(product.get("title") or fallback_title) or "Untitled",
            source="audible",
            confidence=0.0,
            subtitle=str(product.get("subtitle", "") or ""),
            series=series_name,
            series_index=series_index,
            asin=asin,
            raw=product,
        )

    def _audible_candidate_from_audnexus(
        self, audnexus_cand: MetadataCandidate, asin: str
    ) -> MetadataCandidate:
        return MetadataCandidate(
            author=audnexus_cand.author,
            title=audnexus_cand.title,
            source="audible",
            confidence=0.0,
            narrator=audnexus_cand.narrator,
            series=audnexus_cand.series,
            series_index=audnexus_cand.series_index,
            subtitle=audnexus_cand.subtitle,
            asin=asin or audnexus_cand.asin,
            isbn=audnexus_cand.isbn,
            language=audnexus_cand.language,
            publisher=audnexus_cand.publisher,
            year=audnexus_cand.year,
            description=audnexus_cand.description,
            cover_url=audnexus_cand.cover_url,
            raw=audnexus_cand.raw,
        )

    def _audible_product_for_asin(self, payload: dict | None, asin: str) -> dict | None:
        for product in self._audible_products(payload):
            if str(product.get("asin", "") or "") == asin:
                return product
        return None

    def probe(self) -> tuple[str | int, str]:
        params = {
            "title": _PROBE_TITLE,
            "author": _PROBE_AUTHOR,
            "num_results": "1",
            "products_sort_by": "Relevance",
            "response_groups": AUDIBLE_RESPONSE_GROUPS,
        }
        url = "https://api.audible.com/1.0/catalog/products?" + urllib.parse.urlencode(params)
        status, _payload, _headers = self.client.request_json("audible", url)
        if status == 200:
            return "ok", "OK"
        return status, f"HTTP {status}"
