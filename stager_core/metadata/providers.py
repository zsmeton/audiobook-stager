from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

from stager_core.metadata.cache import ApiCache
from stager_core.metadata.normalize import (
    normalize_author,
    normalize_title,
    provider_text,
    split_subtitle,
)
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

AUDIBLE_RESPONSE_GROUPS = "product_desc,product_attrs,contributors,series,media,product_extended_attrs"
MAM_SEARCH_URL = "https://www.myanonamouse.net/tor/js/loadSearchJSONbasic.php"


_RESEARCH_ENV_KEYS = (
    "STAGER_MAM_ID",
    "MAM_ID",
    "GOOGLE_BOOKS_API_KEY",
    "METADATA_CONTACT_EMAIL",
)


def _load_dotenv_if_needed() -> None:
    """Load research provider keys from repo .env when not already in the environment."""
    import os
    from pathlib import Path

    pending = {k for k in _RESEARCH_ENV_KEYS if k not in os.environ}
    if not pending:
        return
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    config_root = (os.environ.get("CONFIG_ROOT") or "").strip()
    if config_root:
        candidates.append(Path(config_root).parent / ".env")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in pending and key not in os.environ:
                    os.environ[key] = val.strip()
                    pending.discard(key)
        except OSError:
            continue
        if not pending:
            return


_MAM_ID_SET_COOKIE_RE = re.compile(r"(?i)\bmam_id=([^;\s]+)")


def stager_mam_cookie_path() -> Path | None:
    """Live cookie file for the Stager home-IP session (never the VPN mam.cookies)."""
    explicit = (os.environ.get("STAGER_MAM_COOKIE_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    stager_root = (
        os.environ.get("STAGER_CONFIG_ROOT") or os.environ.get("STAGING_CONFIG_ROOT") or ""
    ).strip()
    if stager_root:
        return Path(stager_root) / "mam.cookies"
    config_root = (os.environ.get("CONFIG_ROOT") or "").strip()
    if config_root:
        return Path(config_root) / "audiobook-stager" / "mam.cookies"
    return None


def persist_stager_mam_cookie(value: str, path: Path | None = None) -> Path | None:
    """Atomically write the rotated Stager mam_id. Returns the path or None."""
    value = (value or "").strip()
    path = path or stager_mam_cookie_path()
    if not value or path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        tmp.write_text(value, encoding="utf-8")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        logger.warning("Failed to persist Stager MAM cookie to %s", path)
        return None
    return path


def extract_mam_id_from_headers(headers: dict[str, str] | None) -> str:
    if not headers:
        return ""
    raw = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    match = _MAM_ID_SET_COOKIE_RE.search(raw)
    return match.group(1).strip() if match else ""


def resolve_stager_mam_id() -> str:
    """Home-IP Stager session: rotated cookie file, then ``STAGER_MAM_ID`` bootstrap."""
    _load_dotenv_if_needed()
    path = stager_mam_cookie_path()
    if path:
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:
            pass
    return (os.environ.get("STAGER_MAM_ID") or "").strip()


def resolve_mam_id() -> str:
    """Resolve MAM session cookie for metadata search.

    Priority:
    1. Stager cookie file (rotated home-IP session under audiobook-stager/)
    2. ``STAGER_MAM_ID`` — bootstrap for Stager / notebook (outside VPN)
    3. ``MAM_ID`` — VPN seedbox session (mam-updater; use with --vpn on host)
    4. ``MAM_COOKIE_FILE`` or ``CONFIG_ROOT/state/mam.cookies`` (usually VPN cookie)
    """
    stager = resolve_stager_mam_id()
    if stager:
        return stager
    _load_dotenv_if_needed()
    direct = (os.environ.get("MAM_ID") or "").strip()
    if direct:
        return direct
    paths: list[Path] = []
    cookie_file = (os.environ.get("MAM_COOKIE_FILE") or "").strip()
    if cookie_file:
        paths.append(Path(cookie_file))
    config_root = (os.environ.get("CONFIG_ROOT") or "").strip()
    if config_root:
        paths.append(Path(config_root) / "state" / "mam.cookies")
    for path in paths:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def mam_search_body(
    title: str = "",
    author: str = "",
    *,
    perpage: int = 5,
) -> dict:
    """Build JSON body for loadSearchJSONbasic.php (audiobooks main_cat 13)."""
    title = (title or "").strip()
    author = (author or "").strip()
    text = " ".join(p for p in [title, author] if p).strip()
    if not text:
        return {}

    if title and author:
        srch_in = ["title", "author", "narrator"]
    elif author:
        srch_in = ["author"]
    else:
        srch_in = ["title", "author", "narrator"]

    return {
        "tor": {
            "text": text,
            "srchIn": srch_in,
            "searchType": "all",
            "searchIn": "torrents",
            "cat": ["0"],
            "main_cat": ["13"],
            "sortType": "default",
            "startNumber": "0",
            "startDate": "",
            "endDate": "",
            "hash": "",
        },
        "perpage": str(max(5, min(int(perpage), 100))),
    }

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


class MetadataProviders:
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
        self.region = region
        self.google_api_key = google_api_key.strip()
        self.mam_id = (mam_id or "").strip()
        if mam_cookie_path is None:
            self.mam_cookie_path = stager_mam_cookie_path()
        elif mam_cookie_path:
            self.mam_cookie_path = Path(mam_cookie_path)
        else:
            self.mam_cookie_path = None
        self._mam_lock = threading.Lock()

    def _maybe_rotate_mam_cookie(self, headers: dict[str, str] | None) -> None:
        rotated = extract_mam_id_from_headers(headers)
        if not rotated:
            return
        with self._mam_lock:
            if rotated == self.mam_id:
                return
            previous_len = len(self.mam_id)
            self.mam_id = rotated
            persisted = persist_stager_mam_cookie(rotated, self.mam_cookie_path)
            logger.info(
                "MAM cookie rotated (len %d -> %d, persisted=%s)",
                previous_len,
                len(rotated),
                bool(persisted),
            )

    # ------------------------------------------------------------------ audnexus
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

    # -------------------------------------------------------------------- audible
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
        audnexus_hits = self.audnexus_book(asin)
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

    # ------------------------------------------------------------------------ mam
    def mam_search(
        self,
        title: str = "",
        author: str = "",
        *,
        perpage: int = 5,
    ) -> list[MetadataCandidate]:
        if not self.mam_id:
            logger.debug("mam_search skipped: STAGER_MAM_ID not configured")
            return []
        body = mam_search_body(title, author, perpage=perpage)
        if not body:
            logger.debug("mam_search skipped: empty query (title=%r author=%r)", title, author)
            return []
        text = body["tor"]["text"]
        cache_key = "search:v3:" + json.dumps(body, sort_keys=True, separators=(",", ":"))
        cached = self.cache.get("mam", cache_key)
        if cached:
            status, cached_body = cached
            if status == 200:
                candidates = self._candidates_from_mam(cached_body)
                self._log_mam_search(text, status, cached_body, candidates, cached=True)
                return candidates
            logger.info(
                "mam_search cache hit with non-200 status=%s query=%r",
                status,
                text,
            )
            return []

        headers = {"Cookie": f"mam_id={self.mam_id}"}
        status, payload, resp_headers = self.client.request_json(
            "mam", MAM_SEARCH_URL, method="POST", json_body=body, headers=headers
        )
        self._maybe_rotate_mam_cookie(resp_headers)
        if status == 200 and isinstance(payload, dict):
            self.cache.put("mam", cache_key, status, json.dumps(payload), ttl_seconds=86400)
            candidates = self._candidates_from_mam(payload)
            self._log_mam_search(text, status, payload, candidates, cached=False)
            return candidates
        if status == 429:
            logger.warning("mam_search rate limited query=%r", text)
            self.cache.put("mam", cache_key, status, "{}", ttl_seconds=300)
        else:
            logger.warning(
                "mam_search failed status=%s query=%r payload_type=%s",
                status,
                text,
                type(payload).__name__,
            )
        return []

    def _log_mam_search(
        self,
        query: str,
        status: int,
        payload: dict | str,
        candidates: list[MetadataCandidate],
        *,
        cached: bool,
    ) -> None:
        source = "cache" if cached else "live"
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                payload = {}
        error = ""
        row_count = 0
        if isinstance(payload, dict):
            error = str(payload.get("error", "") or "")
            rows = payload.get("data")
            if isinstance(rows, list):
                row_count = len(rows)
        if candidates:
            hits = ", ".join(
                f"{c.author!r} / {c.title!r}" for c in candidates[:3]
            )
            suffix = f" (+{len(candidates) - 3} more)" if len(candidates) > 3 else ""
            logger.info(
                "mam_search %s status=%s query=%r rows=%d candidates=%d hits=[%s%s]",
                source,
                status,
                query,
                row_count,
                len(candidates),
                hits,
                suffix,
            )
        elif error:
            logger.info(
                "mam_search %s status=%s query=%r rows=%d error=%r",
                source,
                status,
                query,
                row_count,
                error,
            )
        else:
            logger.info(
                "mam_search %s status=%s query=%r rows=%d candidates=0",
                source,
                status,
                query,
                row_count,
            )

    @staticmethod
    def _parse_mam_info(value: object) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}

    def _candidates_from_mam(self, payload: dict | str) -> list[MetadataCandidate]:
        if isinstance(payload, str):
            payload = json.loads(payload)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        candidates: list[MetadataCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("name") or "")
            authors = self._parse_mam_info(row.get("author_info"))
            narrators = self._parse_mam_info(row.get("narrator_info"))
            series = self._parse_mam_info(row.get("series_info"))

            author_name = ", ".join(str(v) for v in authors.values() if v)
            narrator_name = ", ".join(str(v) for v in narrators.values() if v)

            series_name = ""
            series_index = ""
            for entry in series.values():
                if isinstance(entry, (list, tuple)) and entry:
                    series_name = str(entry[0])
                    if len(entry) > 1:
                        series_index = str(entry[1])
                elif entry:
                    series_name = str(entry)
                if series_name:
                    break

            series_name = provider_text(series_name)
            series_index = provider_text(series_index)

            main_title, subtitle = split_subtitle(_clean_title(title))
            candidates.append(
                MetadataCandidate(
                    author=_clean_author(author_name) or "Unknown Author",
                    title=main_title or _clean_title(title) or "Untitled",
                    source="mam",
                    confidence=0.0,
                    narrator=narrator_name,
                    series=series_name,
                    series_index=series_index,
                    subtitle=subtitle,
                    language=str(row.get("language", "") or ""),
                    raw=row,
                )
            )
        return candidates

    # ------------------------------------------------------------------ openlibrary
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

    # ------------------------------------------------------------------ google books
    def google_books_search(self, title: str = "", author: str = "") -> list[MetadataCandidate]:
        if not self.google_api_key:
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

    # -------------------------------------------------------- title-only pass wrappers
    def audible_search_title_only(self, title: str) -> list[MetadataCandidate]:
        """Explicit title-only Audible search; author param omitted from API request."""
        return self.audible_search((title or "").strip(), "")

    def mam_search_title_only(self, title: str, *, perpage: int = 5) -> list[MetadataCandidate]:
        """Explicit title-only MAM search; author field omitted from query body."""
        return self.mam_search((title or "").strip(), "", perpage=perpage)

    def openlibrary_search_title_only(self, title: str) -> list[MetadataCandidate]:
        """Explicit title-only Open Library search; author param omitted."""
        return self.openlibrary_search((title or "").strip(), "")

    def google_books_search_title_only(self, title: str) -> list[MetadataCandidate]:
        """Explicit title-only Google Books search; inauthor omitted from query."""
        return self.google_books_search((title or "").strip(), "")

    # ------------------------------------------------------- audnexus author verify
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

    # ------------------------------------------------------------------ probes
    def probe_connectivity(self, provider_id: str) -> tuple[str | int, str]:
        """Return (status, message) where status is 'ok', 'skipped', or HTTP code."""
        import urllib.parse

        if provider_id == "audnexus":
            url = f"https://api.audnex.us/books/{_PROBE_ASIN}?region={self.region}"
            status, _payload, _headers = self.client.request_json("audnexus", url)
            if status == 200:
                return "ok", "OK"
            return status, f"HTTP {status}"

        if provider_id == "audible":
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

        if provider_id == "openlibrary":
            url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(
                {"title": _PROBE_TITLE, "author": _PROBE_AUTHOR, "limit": "1"}
            )
            status, _payload, _headers = self.client.request_json("openlibrary", url)
            if status == 200:
                return "ok", "OK"
            return status, f"HTTP {status}"

        if provider_id == "google_books":
            if not self.google_api_key:
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

        if provider_id == "mam":
            if not self.mam_id:
                return "skipped", "API key not configured"
            body = mam_search_body(_PROBE_TITLE, _PROBE_AUTHOR, perpage=1)
            status, _payload, resp_headers = self.client.request_json(
                "mam",
                MAM_SEARCH_URL,
                method="POST",
                json_body=body,
                headers={"Cookie": f"mam_id={self.mam_id}"},
            )
            self._maybe_rotate_mam_cookie(resp_headers)
            if status == 200:
                return "ok", "OK"
            return status, f"HTTP {status}"

        return 0, "unknown provider"


_PROBE_TITLE = "Red Rising"
_PROBE_AUTHOR = "Pierce Brown"
_PROBE_ASIN = "B00I2VWW5U"
