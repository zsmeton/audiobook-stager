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


def list_provider_status() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for spec in PROVIDER_DEFS:
        env_key = spec.get("env_key")
        configured = _env_configured(env_key)
        requires_key = bool(spec.get("requires_key"))
        enabled = configured if requires_key else True
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

    if spec.get("requires_key") and not _env_configured(spec.get("env_key")):
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
