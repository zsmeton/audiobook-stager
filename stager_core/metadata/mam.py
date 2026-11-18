from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

from stager_core.metadata.cache import ApiCache
from stager_core.metadata.normalize import (
    normalize_author,
    normalize_title,
    provider_text,
    split_subtitle,
)
from stager_core.metadata.provider_registry import empty_key_blocks
from stager_core.metadata.ratelimit import RateLimitedClient
from stager_core.metadata.types import MetadataCandidate

logger = logging.getLogger(__name__)

MAM_SEARCH_URL = "https://www.myanonamouse.net/tor/js/loadSearchJSONbasic.php"
_PROBE_TITLE = "Red Rising"
_PROBE_AUTHOR = "Pierce Brown"

_RESEARCH_ENV_KEYS = (
    "STAGER_MAM_ID",
    "MAM_ID",
    "GOOGLE_BOOKS_API_KEY",
    "METADATA_CONTACT_EMAIL",
)

_MAM_ID_SET_COOKIE_RE = re.compile(r"(?i)\bmam_id=([^;\s]+)")


def _load_dotenv_if_needed() -> None:
    """Load research provider keys from repo .env when not already in the environment."""
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


def _clean_title(title: str) -> str:
    return normalize_title(provider_text(title or ""))


def _clean_author(author: str) -> str:
    return normalize_author(provider_text(author or ""))


class MamProvider:
    def __init__(
        self,
        client: RateLimitedClient,
        cache: ApiCache,
        *,
        mam_id: str = "",
        mam_cookie_path: Path | str | None = None,
    ):
        self.client = client
        self.cache = cache
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

    def mam_search(
        self,
        title: str = "",
        author: str = "",
        *,
        perpage: int = 5,
    ) -> list[MetadataCandidate]:
        if empty_key_blocks("mam", self.mam_id):
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

    def mam_search_title_only(self, title: str, *, perpage: int = 5) -> list[MetadataCandidate]:
        """Explicit title-only MAM search; author field omitted from query body."""
        return self.mam_search((title or "").strip(), "", perpage=perpage)

    def probe(self) -> tuple[str | int, str]:
        if empty_key_blocks("mam", self.mam_id):
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
