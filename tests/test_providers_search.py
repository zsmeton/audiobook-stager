from __future__ import annotations

import json
import unittest

from stager_core.metadata.providers import MetadataProviders, mam_search_body


class FakeCache:
    """No-op cache so providers always hit the (mocked) client."""

    def get(self, provider, cache_key):
        return None

    def put(self, *args, **kwargs):
        return None

    def put_permanent(self, *args, **kwargs):
        return None


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request_json(
        self, provider, url, *, method="GET", data=None, json_body=None, headers=None, max_attempts=4
    ):
        self.calls.append(
            {
                "provider": provider,
                "url": url,
                "method": method,
                "data": data,
                "json_body": json_body,
                "headers": headers,
            }
        )
        return self.responses.get(provider, (0, None, {}))


AUDNEXUS_BOOK = {
    "asin": "B0079OFY1U",
    "title": "Red Rising",
    "subtitle": "Book 1 of the Red Rising Saga",
    "authors": [{"name": "Pierce Brown"}],
    "narrators": [{"name": "Tim Gerard Reynolds"}],
    "seriesPrimary": {"name": "Red Rising Saga", "position": "1"},
    "language": "english",
    "publisherName": "Recorded Books",
    "releaseDate": "2014-01-28",
    "image": "https://example.com/cover.jpg",
}

AUDIBLE_PRODUCTS = {
    "products": [
        {"asin": "B0079OFY1U", "title": "Red Rising", "authors": [{"name": "Pierce Brown"}]},
        {"asin": "BOGUS00002", "title": "Unrelated", "authors": [{"name": "Someone"}]},
    ]
}

MAM_RESPONSE = {
    "found": 1,
    "data": [
        {
            "title": "Red Rising",
            "author_info": json.dumps({"123": "Pierce Brown"}),
            "narrator_info": json.dumps({"55": "Tim Gerard Reynolds"}),
            "series_info": json.dumps({"9": ["Red Rising Saga", "1"]}),
        }
    ],
}


class AudibleSearchTests(unittest.TestCase):
    def test_audible_to_asin_to_audnexus(self) -> None:
        client = FakeClient(
            {
                "audible": (200, AUDIBLE_PRODUCTS, {}),
                "audnexus": (200, AUDNEXUS_BOOK, {}),
            }
        )
        providers = MetadataProviders(client, FakeCache())
        results = providers.audible_search("Red Rising", "Pierce Brown")
        self.assertEqual(len(results), 1)
        cand = results[0]
        self.assertEqual(cand.source, "audible")
        self.assertEqual(cand.title, "Red Rising")
        self.assertEqual(cand.author, "Pierce Brown")
        self.assertEqual(cand.asin, "B0079OFY1U")
        self.assertEqual(cand.narrator, "Tim Gerard Reynolds")
        self.assertEqual(cand.series, "Red Rising Saga")
        # The chosen ASIN must be the best-matching product, not the bogus one.
        audnexus_call = next(c for c in client.calls if c["provider"] == "audnexus")
        self.assertIn("B0079OFY1U", audnexus_call["url"])

    def test_audible_fallback_product_source(self) -> None:
        client = FakeClient(
            {
                "audible": (200, AUDIBLE_PRODUCTS, {}),
                "audnexus": (404, {}, {}),
            }
        )
        providers = MetadataProviders(client, FakeCache())
        results = providers.audible_search("Red Rising", "Pierce Brown")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "audible")

    def test_audible_empty_degrades(self) -> None:
        client = FakeClient({"audible": (200, {"products": []}, {})})
        providers = MetadataProviders(client, FakeCache())
        self.assertEqual(providers.audible_search("Nothing", ""), [])


class MamSearchTests(unittest.TestCase):
    def test_disabled_without_cookie(self) -> None:
        client = FakeClient({"mam": (200, MAM_RESPONSE, {})})
        providers = MetadataProviders(client, FakeCache(), mam_id="")
        self.assertEqual(providers.mam_search("Red Rising", "Pierce Brown"), [])
        self.assertEqual(client.calls, [])

    def test_parses_author_narrator_series(self) -> None:
        client = FakeClient({"mam": (200, MAM_RESPONSE, {})})
        providers = MetadataProviders(client, FakeCache(), mam_id="cookie-value")
        results = providers.mam_search("Red Rising", "Pierce Brown")
        self.assertEqual(len(results), 1)
        cand = results[0]
        self.assertEqual(cand.source, "mam")
        self.assertEqual(cand.title, "Red Rising")
        self.assertEqual(cand.author, "Pierce Brown")
        self.assertEqual(cand.narrator, "Tim Gerard Reynolds")
        self.assertEqual(cand.series, "Red Rising Saga")
        self.assertEqual(cand.series_index, "1")

    def test_sends_cookie_and_post(self) -> None:
        client = FakeClient({"mam": (200, MAM_RESPONSE, {})})
        providers = MetadataProviders(client, FakeCache(), mam_id="abc123")
        providers.mam_search("Red Rising", "Pierce Brown")
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["headers"]["Cookie"], "mam_id=abc123")
        body = call["json_body"]
        self.assertEqual(body["tor"]["text"], "Red Rising Pierce Brown")
        self.assertEqual(body["tor"]["main_cat"], ["13"])
        self.assertEqual(body["tor"]["cat"], ["0"])
        self.assertIn("title", body["tor"]["srchIn"])
        self.assertIn("author", body["tor"]["srchIn"])
        self.assertNotIn("browseStart", body["tor"])
        self.assertEqual(body["perpage"], "5")


class TitleOnlyWrapperTests(unittest.TestCase):
    def test_audible_title_only_omits_author_param(self) -> None:
        client = FakeClient(
            {
                "audible": (200, AUDIBLE_PRODUCTS, {}),
                "audnexus": (200, AUDNEXUS_BOOK, {}),
            }
        )
        providers = MetadataProviders(client, FakeCache())
        providers.audible_search_title_only("Red Rising")
        audible_url = next(c["url"] for c in client.calls if c["provider"] == "audible")
        self.assertIn("title=Red+Rising", audible_url)
        self.assertNotIn("author=", audible_url)

    def test_mam_title_only_uses_title_fields(self) -> None:
        client = FakeClient({"mam": (200, MAM_RESPONSE, {})})
        providers = MetadataProviders(client, FakeCache(), mam_id="abc123")
        providers.mam_search_title_only("Red Rising")
        body = client.calls[0]["json_body"]
        self.assertEqual(body["tor"]["text"], "Red Rising")
        self.assertEqual(body["tor"]["srchIn"], ["title", "author", "narrator"])

    def test_openlibrary_title_only_omits_author_param(self) -> None:
        client = FakeClient({"openlibrary": (200, {"docs": []}, {})})
        providers = MetadataProviders(client, FakeCache())
        providers.openlibrary_search_title_only("Red Rising")
        url = client.calls[0]["url"]
        self.assertIn("title=Red+Rising", url)
        self.assertNotIn("author=", url)

    def test_google_title_only_omits_inauthor(self) -> None:
        client = FakeClient({"google_books": (200, {"items": []}, {})})
        providers = MetadataProviders(client, FakeCache(), google_api_key="k")
        providers.google_books_search_title_only("Red Rising")
        url = client.calls[0]["url"]
        self.assertIn("intitle%3ARed+Rising", url)
        self.assertNotIn("inauthor", url)

    def test_title_only_empty_title_returns_without_request(self) -> None:
        client = FakeClient({})
        providers = MetadataProviders(client, FakeCache(), mam_id="x", google_api_key="k")
        self.assertEqual(providers.audible_search_title_only(""), [])
        self.assertEqual(providers.mam_search_title_only(""), [])
        self.assertEqual(providers.openlibrary_search_title_only(""), [])
        self.assertEqual(providers.google_books_search_title_only(""), [])
        self.assertEqual(client.calls, [])


class MamSearchBodyTests(unittest.TestCase):
    def test_author_only_searches_author_field(self) -> None:
        body = mam_search_body("", "Martha Wells")
        self.assertEqual(body["tor"]["text"], "Martha Wells")
        self.assertEqual(body["tor"]["srchIn"], ["author"])

    def test_title_only_keeps_title_fields(self) -> None:
        body = mam_search_body("Red Rising", "")
        self.assertEqual(body["tor"]["srchIn"], ["title", "author", "narrator"])

    def test_combined_searches_all_fields(self) -> None:
        body = mam_search_body("Red Rising", "Pierce Brown", perpage=20)
        self.assertEqual(body["tor"]["srchIn"], ["title", "author", "narrator"])
        self.assertEqual(body["perpage"], "20")


if __name__ == "__main__":
    unittest.main()
