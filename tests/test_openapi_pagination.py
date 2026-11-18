"""OpenAPI lists pagination query parameters the handlers already accept.

Reads app.openapi(). Does not bind a port and does not open the network.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from starlette.routing import Mount

from app.main import STATIC_DIR, app, index


def _operations(schema: dict) -> list[tuple[str, str, dict]]:
    found: list[tuple[str, str, dict]] = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            found.append((method.upper(), path, operation))
    return found


def _query_params(operation: dict) -> dict[str, dict]:
    return {
        param["name"]: param
        for param in operation.get("parameters") or []
        if param.get("in") == "query"
    }


class OpenApiPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = app.openapi()

    def test_app_title_and_version_are_explicit(self) -> None:
        info = self.schema["info"]
        self.assertEqual(info["title"], "Audiobook Stager")
        self.assertEqual(info["version"], "0.1.136")

    def test_book_list_documents_limit_and_offset(self) -> None:
        operation = self.schema["paths"]["/api/books"]["get"]
        params = _query_params(operation)

        self.assertEqual(set(params), {
            "status",
            "q",
            "low_confidence",
            "section",
            "partitioned",
            "limit",
            "offset",
        })
        self.assertIs(params["limit"]["required"], False)
        self.assertEqual(params["limit"]["schema"]["type"], "integer")
        self.assertEqual(params["limit"]["schema"]["default"], 500)
        self.assertIs(params["offset"]["required"], False)
        self.assertEqual(params["offset"]["schema"]["type"], "integer")
        self.assertEqual(params["offset"]["schema"]["default"], 0)
        self.assertIs(params["status"]["required"], False)
        self.assertIs(params["q"]["required"], False)

    def test_pagination_parameters_match_handlers_that_already_accept_them(self) -> None:
        limit_ops: set[str] = set()
        offset_ops: set[str] = set()
        for method, path, operation in _operations(self.schema):
            names = set(_query_params(operation))
            label = f"{method} {path}"
            if "limit" in names:
                limit_ops.add(label)
            if "offset" in names:
                offset_ops.add(label)

        self.assertEqual(limit_ops, {
            "GET /api/auto/feedback",
            "GET /api/books",
            "GET /api/books/{book_id}/decisions",
            "GET /api/decisions",
        })
        self.assertEqual(offset_ops, {
            "GET /api/auto/feedback",
            "GET /api/books",
        })

        feedback = _query_params(self.schema["paths"]["/api/auto/feedback"]["get"])
        self.assertEqual(set(feedback), {"decision", "limit", "offset"})
        self.assertEqual(feedback["limit"]["schema"]["default"], 100)
        self.assertEqual(feedback["offset"]["schema"]["default"], 0)

        book_decisions = _query_params(
            self.schema["paths"]["/api/books/{book_id}/decisions"]["get"]
        )
        self.assertEqual(set(book_decisions), {"limit"})
        self.assertEqual(book_decisions["limit"]["schema"]["default"], 50)

        decisions = _query_params(self.schema["paths"]["/api/decisions"]["get"])
        self.assertEqual(set(decisions), {"since", "source", "status", "limit"})
        self.assertEqual(decisions["limit"]["schema"]["default"], 200)

        for path in ("/api/conflicts", "/api/merges", "/api/auto/review"):
            self.assertEqual(_query_params(self.schema["paths"][path]["get"]), {})

    def test_static_index_route_remains(self) -> None:
        by_path = {getattr(route, "path", None): route for route in app.routes}
        self.assertIn("/", by_path)
        self.assertIn("/openapi.json", by_path)
        self.assertIsInstance(by_path["/static"], Mount)
        page = index()
        self.assertEqual(Path(page.path), STATIC_DIR / "index.html")
        self.assertTrue(Path(page.path).is_file())
