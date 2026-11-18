"""D02 empty-key skip. No network: callables and fake clients only."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from stager_core.metadata.lookup import MetadataLookupService
from stager_core.metadata.openlibrary import OpenLibraryProvider
from stager_core.metadata.provider_registry import PROVIDER_DEFS, invoke_provider, list_provider_status
from stager_core.metadata.types import MetadataCandidate


_LATER = {
    "id": "later_catalog",
    "label": "Later Catalog",
    "requires_key": True,
    "env_key": "LATER_CATALOG_API_KEY",
}

_BLANK = {
    "LATER_CATALOG_API_KEY": "",
    "METADATA_CONTACT_EMAIL": "",
    "GOOGLE_BOOKS_API_KEY": "",
    "STAGER_MAM_ID": "",
    "MAM_ID": "",
    "STAGER_MAM_COOKIE_FILE": r"Z:\__no_stager_mam_cookies__",
}


def _hit(source: str) -> MetadataCandidate:
    return MetadataCandidate(
        author="Pierce Brown",
        title="Red Rising",
        source=source,
        confidence=0.0,
    )


class _RecordingProviders:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.google_api_key = ""
        self.mam_id = ""

    def audible_search(self, title: str = "", author: str = ""):
        self.calls.append("audible")
        return [_hit("audible")]

    def mam_search(self, title: str = "", author: str = "", *, perpage: int = 5):
        self.calls.append("mam")
        return [_hit("mam")]

    def google_books_search(self, title: str = "", author: str = ""):
        self.calls.append("google_books")
        return [_hit("google_books")]

    def openlibrary_search(self, title: str = "", author: str = ""):
        self.calls.append("openlibrary")
        return [_hit("openlibrary")]


class _Cache:
    def get(self, *args, **kwargs):
        return None

    def put(self, *args, **kwargs):
        return None

    def put_permanent(self, *args, **kwargs):
        return None


class _Client:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def request_json(self, provider, url, **kwargs):
        self.calls.append(provider)
        return 200, {"docs": [{"title": "Red Rising", "author_name": ["Pierce Brown"]}]}, {}


class EmptyKeySkipTests(unittest.TestCase):
    def setUp(self) -> None:
        PROVIDER_DEFS.append(_LATER)

    def tearDown(self) -> None:
        if _LATER in PROVIDER_DEFS:
            PROVIDER_DEFS.remove(_LATER)

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_later_requires_key_provider_is_not_called_when_key_is_empty(self) -> None:
        called: list[str] = []

        def later(title: str = "", author: str = ""):
            called.append("later")
            return [_hit("later_catalog")]

        def openlibrary(title: str = "", author: str = ""):
            called.append("openlibrary")
            return [_hit("openlibrary")]

        def audible(title: str = "", author: str = ""):
            called.append("audible")
            return [_hit("audible")]

        def audnexus(title: str = "", author: str = ""):
            called.append("audnexus")
            return [_hit("audnexus")]

        skipped = invoke_provider("later_catalog", later, "Red Rising", "Pierce Brown")
        kept_openlibrary = invoke_provider("openlibrary", openlibrary, "Red Rising", "Pierce Brown")
        kept_audible = invoke_provider("audible", audible, "Red Rising", "Pierce Brown")
        kept_audnexus = invoke_provider("audnexus", audnexus, "Red Rising", "Pierce Brown")
        status = {item["id"]: item for item in list_provider_status()}

        self.assertEqual(skipped, [])
        self.assertNotIn("later", called)
        self.assertEqual([item.source for item in kept_openlibrary], ["openlibrary"])
        self.assertEqual([item.source for item in kept_audible], ["audible"])
        self.assertEqual([item.source for item in kept_audnexus], ["audnexus"])
        self.assertEqual(called, ["openlibrary", "audible", "audnexus"])
        self.assertTrue(status["later_catalog"]["requires_key"])
        self.assertFalse(status["later_catalog"]["configured"])
        self.assertFalse(status["later_catalog"]["enabled"])
        self.assertTrue(status["openlibrary"]["enabled"])
        self.assertFalse(status["openlibrary"]["requires_key"])
        self.assertTrue(status["audnexus"]["enabled"])
        self.assertTrue(status["audible"]["enabled"])

    @patch.dict(os.environ, {**_BLANK, "LATER_CATALOG_API_KEY": "present"}, clear=False)
    def test_later_requires_key_provider_is_called_when_key_is_set(self) -> None:
        called: list[str] = []

        def later(title: str = "", author: str = ""):
            called.append("later")
            return [_hit("later_catalog")]

        found = invoke_provider("later_catalog", later, "Red Rising", "Pierce Brown")
        self.assertEqual(called, ["later"])
        self.assertEqual([item.source for item in found], ["later_catalog"])

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_lookup_keeps_keyless_providers_when_credentials_are_empty(self) -> None:
        providers = _RecordingProviders()
        svc = MetadataLookupService.__new__(MetadataLookupService)
        svc.providers = providers

        pooled = svc._external_candidates("Red Rising", "Pierce Brown")

        self.assertEqual(providers.calls, ["audible", "openlibrary"])
        self.assertEqual([item.source for item in pooled], ["audible", "openlibrary"])

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_blank_contact_email_still_calls_openlibrary(self) -> None:
        client = _Client()
        hits = OpenLibraryProvider(client, _Cache()).openlibrary_search("Red Rising", "Pierce Brown")
        self.assertEqual(client.calls, ["openlibrary"])
        self.assertEqual(hits[0].title, "Red Rising")
        self.assertEqual(hits[0].source, "openlibrary")
