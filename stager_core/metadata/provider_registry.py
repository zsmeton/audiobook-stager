from __future__ import annotations

import os
from typing import Any

PROVIDER_DEFS: list[dict[str, Any]] = [
    {"id": "audnexus", "label": "Audnexus", "requires_key": False},
    {"id": "audible", "label": "Audible", "requires_key": False},
    {"id": "openlibrary", "label": "Open Library", "requires_key": False},
    {"id": "google_books", "label": "Google Books", "requires_key": True, "env_key": "GOOGLE_BOOKS_API_KEY"},
    {"id": "mam", "label": "MAM", "requires_key": True, "env_key": "STAGER_MAM_ID"},
]

_PROBE_TITLE = "Red Rising"
_PROBE_AUTHOR = "Pierce Brown"
_PROBE_ASIN = "B00I2VWW5U"


def _env_configured(env_key: str | None) -> bool:
    if not env_key:
        return True
    if env_key == "STAGER_MAM_ID":
        from stager_core.metadata.providers import resolve_stager_mam_id

        return bool(resolve_stager_mam_id())
    return bool(os.environ.get(env_key, "").strip())


def empty_key_blocks(provider_id: str, credential: str | None = None) -> bool:
    """True when a requires_key provider has no credential and must not be called.

    Keyless providers are never blocked. A blank contact email is not a credential.
    """
    spec = next((item for item in PROVIDER_DEFS if item["id"] == provider_id), None)
    if spec is None or not spec.get("requires_key"):
        return False
    if credential is None:
        env_key = spec.get("env_key")
        if not env_key:
            return True
        return not _env_configured(env_key)
    return not str(credential).strip()


_INSTANCE_CREDENTIAL_ATTR = {
    "google_books": "google_api_key",
    "mam": "mam_id",
}


def _call_credential(provider_id: str, providers: Any, credential: str | None) -> str | None:
    if credential is not None:
        return credential
    attr = _INSTANCE_CREDENTIAL_ATTR.get(provider_id)
    if providers is not None and attr is not None:
        if hasattr(providers, attr):
            value = getattr(providers, attr)
            return "" if value is None else str(value)
        return ""
    return None


def invoke_provider(
    provider_id: str,
    fn: Any,
    /,
    *args: Any,
    providers: Any = None,
    credential: str | None = None,
    **kwargs: Any,
) -> Any:
    """Call ``fn`` unless D02 skips this provider for an empty credential."""
    secret = _call_credential(provider_id, providers, credential)
    if empty_key_blocks(provider_id, secret):
        return []
    return fn(*args, **kwargs)


def list_provider_status() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for spec in PROVIDER_DEFS:
        env_key = spec.get("env_key")
        configured = _env_configured(env_key)
        requires_key = bool(spec.get("requires_key"))
        enabled = not empty_key_blocks(spec["id"])
        items.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "requires_key": requires_key,
                "configured": configured,
                "enabled": enabled,
            }
        )
    return items


def probe_provider(providers: Any, provider_id: str) -> dict[str, Any]:
    spec = next((p for p in PROVIDER_DEFS if p["id"] == provider_id), None)
    if spec is None:
        return {"id": provider_id, "status": "error", "http_status": None, "message": "unknown provider"}

    if empty_key_blocks(provider_id):
        return {
            "id": provider_id,
            "status": "skipped",
            "http_status": None,
            "message": "API key not configured",
        }

    status, message = providers.probe_connectivity(provider_id)
    if status == "skipped":
        return {"id": provider_id, "status": "skipped", "http_status": None, "message": message}
    if status == "ok":
        return {"id": provider_id, "status": "ok", "http_status": 200, "message": message or "OK"}
    return {
        "id": provider_id,
        "status": "error",
        "http_status": status if isinstance(status, int) else None,
        "message": message or "Request failed",
    }


def test_all_providers(providers: Any) -> list[dict[str, Any]]:
    return [probe_provider(providers, spec["id"]) for spec in PROVIDER_DEFS]
