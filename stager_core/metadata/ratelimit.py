from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from email.message import Message


@dataclass
class ProviderState:
    min_interval_s: float
    last_call_at: float = 0.0
    cooldown_until: float = 0.0
    consecutive_429: int = 0
    consecutive_timeouts: int = 0
    disabled_until: float = 0.0
    wait_message: str = ""
    # Leaky bucket: cap requests within a rolling window (0 = disabled).
    bucket_capacity: int = 0
    bucket_window_s: float = 60.0
    recent_calls: deque = field(default_factory=deque)


def http_headers_dict(msg: Message | None) -> dict[str, str]:
    """Flatten HTTP headers, keeping every Set-Cookie value.

    ``dict(msg.items())`` would keep only the last Set-Cookie, dropping ``mam_id``
    if another cookie is sent after it.
    """
    if msg is None:
        return {}
    headers = {str(k): str(v) for k, v in msg.items()}
    getter = getattr(msg, "get_all", None)
    cookies = getter("Set-Cookie") if callable(getter) else None
    if cookies:
        headers["Set-Cookie"] = "\n".join(str(c) for c in cookies)
    return headers


class RateLimitedClient:
    def __init__(
        self,
        *,
        audnexus_min_ms: int = 500,
        openlibrary_min_ms: int = 1000,
        google_min_ms: int = 1000,
        audible_min_ms: int = 1000,
        mam_requests_per_minute: int = 120,
        user_agent: str = "SeedboxAudiobookStager/0.1",
    ):
        self.user_agent = user_agent
        self.providers: dict[str, ProviderState] = {
            "audnexus": ProviderState(min_interval_s=audnexus_min_ms / 1000.0),
            "openlibrary": ProviderState(min_interval_s=openlibrary_min_ms / 1000.0),
            "google_books": ProviderState(min_interval_s=google_min_ms / 1000.0),
            "audible": ProviderState(min_interval_s=audible_min_ms / 1000.0),
            "mam": ProviderState(
                min_interval_s=0.0,
                bucket_capacity=max(1, int(mam_requests_per_minute)),
                bucket_window_s=60.0,
            ),
        }

    def provider_wait_seconds(self, provider: str) -> float:
        state = self.providers.get(provider)
        if not state:
            return 0.0
        now = time.monotonic()
        waits = []
        if state.disabled_until > now:
            waits.append(state.disabled_until - now)
        if state.cooldown_until > now:
            waits.append(state.cooldown_until - now)
        if state.last_call_at:
            waits.append(max(0.0, state.min_interval_s - (now - state.last_call_at)))
        if state.bucket_capacity > 0:
            window_start = now - state.bucket_window_s
            while state.recent_calls and state.recent_calls[0] < window_start:
                state.recent_calls.popleft()
            if len(state.recent_calls) >= state.bucket_capacity:
                waits.append(state.recent_calls[0] + state.bucket_window_s - now)
        return max(waits) if waits else 0.0

    def wait_status(self) -> str:
        messages = []
        for name, state in self.providers.items():
            wait = self.provider_wait_seconds(name)
            if wait > 0.5:
                messages.append(f"{name}: {int(wait)}s")
        return "; ".join(messages)

    def _sleep_until_ready(self, provider: str) -> None:
        wait = self.provider_wait_seconds(provider)
        if wait > 0:
            self.providers[provider].wait_message = f"waiting on {provider}: {int(wait)}s"
            time.sleep(wait)
        self.providers[provider].wait_message = ""

    def _record_success(self, provider: str) -> None:
        state = self.providers[provider]
        now = time.monotonic()
        state.last_call_at = now
        state.consecutive_429 = 0
        state.consecutive_timeouts = 0
        if state.bucket_capacity > 0:
            state.recent_calls.append(now)

    def _parse_retry_seconds(self, headers: dict[str, str], body: str) -> int:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return max(1, int(retry_after))
            except ValueError:
                pass
        reset = headers.get("X-Ratelimit-Reset") or headers.get("x-ratelimit-reset")
        if reset:
            try:
                return max(1, int(reset))
            except ValueError:
                pass
        match = re.search(r"retry in (\d+) seconds?", body, re.IGNORECASE)
        if match:
            return max(1, int(match.group(1)))
        return 12

    def _record_429(self, provider: str, headers: dict[str, str], body: str) -> int:
        state = self.providers[provider]
        state.consecutive_429 += 1
        delay = self._parse_retry_seconds(headers, body)
        if provider == "audnexus" and state.consecutive_429 >= 3:
            delay = max(delay, 60)
        if provider == "openlibrary":
            delay = max(delay, 60)
        if provider == "google_books":
            delay = max(delay, 60)
            if "per day" in body.lower() or "defaultPerDayPerProject" in body:
                state.disabled_until = time.monotonic() + 86400
        state.cooldown_until = time.monotonic() + delay + random.uniform(0.1, 0.5)
        return delay

    def _record_timeout(self, provider: str) -> None:
        state = self.providers[provider]
        state.consecutive_timeouts += 1
        if provider == "openlibrary" and state.consecutive_timeouts >= 2:
            state.cooldown_until = time.monotonic() + 120

    def request_json(
        self,
        provider: str,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, object] | bytes | None = None,
        json_body: dict | None = None,
        headers: dict[str, str] | None = None,
        max_attempts: int = 4,
    ) -> tuple[int, dict | list | None, dict[str, str]]:
        state = self.providers.get(provider)
        if not state:
            raise ValueError(f"unknown provider: {provider}")
        if state.disabled_until > time.monotonic():
            return 429, None, {}

        method = method.upper()
        body_bytes: bytes | None = None
        req_headers = {"User-Agent": self.user_agent}
        if isinstance(data, (bytes, bytearray)):
            body_bytes = bytes(data)
        elif json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif isinstance(data, dict):
            body_bytes = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"
        if headers:
            req_headers.update(headers)

        last_status = 0
        last_headers: dict[str, str] = {}
        for attempt in range(max_attempts):
            self._sleep_until_ready(provider)
            req = urllib.request.Request(
                url, data=body_bytes, headers=req_headers, method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    headers = http_headers_dict(resp.headers)
                    self._record_success(provider)
                    return resp.status, json.loads(body) if body else None, headers
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_status = exc.code
                last_headers = http_headers_dict(exc.headers)
                if exc.code == 429:
                    delay = self._record_429(provider, last_headers, body)
                    if attempt + 1 >= max_attempts:
                        return 429, None, last_headers
                    time.sleep(delay + min(2 ** attempt, 30))
                    continue
                try:
                    payload = json.loads(body) if body else None
                except json.JSONDecodeError:
                    payload = {"raw": body}
                self._record_success(provider)
                return exc.code, payload, last_headers
            except (TimeoutError, urllib.error.URLError):
                self._record_timeout(provider)
                if attempt + 1 >= max_attempts:
                    return 0, None, {}
                time.sleep(min(2 ** attempt, 30))
        return last_status, None, last_headers
