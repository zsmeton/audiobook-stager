from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stager_core.metadata.providers import (
    MetadataProviders,
    extract_mam_id_from_headers,
    persist_stager_mam_cookie,
    resolve_mam_id,
    resolve_stager_mam_id,
    stager_mam_cookie_path,
)
from stager_core.metadata.ratelimit import http_headers_dict
from email.message import Message

from tests.test_providers_search import FakeCache, FakeClient, MAM_RESPONSE


class ExtractMamCookieTests(unittest.TestCase):
    def test_extracts_mam_id_from_set_cookie(self) -> None:
        self.assertEqual(
            extract_mam_id_from_headers({"Set-Cookie": "mam_id=abc123; Path=/; HttpOnly"}),
            "abc123",
        )

    def test_extracts_from_multiline_set_cookie(self) -> None:
        raw = "other=1; Path=/\nmam_id=rotated-value; Path=/\nsession=x"
        self.assertEqual(extract_mam_id_from_headers({"Set-Cookie": raw}), "rotated-value")

    def test_empty_without_mam_id(self) -> None:
        self.assertEqual(extract_mam_id_from_headers({"Set-Cookie": "foo=bar"}), "")
        self.assertEqual(extract_mam_id_from_headers({}), "")


class HttpHeadersDictTests(unittest.TestCase):
    def test_keeps_all_set_cookie_values(self) -> None:
        msg = Message()
        msg.add_header("Set-Cookie", "mam_id=keep-me; Path=/")
        msg.add_header("Set-Cookie", "other=1; Path=/")
        headers = http_headers_dict(msg)
        self.assertIn("mam_id=keep-me", headers["Set-Cookie"])
        self.assertIn("other=1", headers["Set-Cookie"])
        self.assertEqual(extract_mam_id_from_headers(headers), "keep-me")


class StagerCookieFileTests(unittest.TestCase):
    def test_explicit_path_wins(self) -> None:
        with patch.dict(
            os.environ,
            {
                "STAGER_MAM_COOKIE_FILE": r"V:\tmp\stager.mam",
                "STAGER_CONFIG_ROOT": r"V:\other",
                "CONFIG_ROOT": r"V:\config",
            },
            clear=False,
        ):
            self.assertEqual(stager_mam_cookie_path(), Path(r"V:\tmp\stager.mam"))

    def test_file_wins_over_env_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "mam.cookies"
            cookie_path.write_text("from-file", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "STAGER_MAM_COOKIE_FILE": str(cookie_path),
                    "STAGER_MAM_ID": "from-env",
                    "MAM_ID": "vpn-cookie",
                },
                clear=False,
            ):
                self.assertEqual(resolve_stager_mam_id(), "from-file")
                self.assertEqual(resolve_mam_id(), "from-file")

    def test_stager_env_wins_over_vpn_cookie(self) -> None:
        with patch.dict(
            os.environ,
            {
                "STAGER_MAM_COOKIE_FILE": str(Path(tempfile.gettempdir()) / "missing-stager-mam.cookies"),
                "STAGER_MAM_ID": "stager-env",
                "MAM_ID": "vpn-cookie",
            },
            clear=False,
        ):
            self.assertEqual(resolve_stager_mam_id(), "stager-env")
            self.assertEqual(resolve_mam_id(), "stager-env")

    def test_persist_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "mam.cookies"
            written = persist_stager_mam_cookie("rotated-id", cookie_path)
            self.assertEqual(written, cookie_path)
            self.assertEqual(cookie_path.read_text(encoding="utf-8"), "rotated-id")


class MamRotationOnSearchTests(unittest.TestCase):
    def test_search_persists_rotated_cookie_and_reuses_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "mam.cookies"
            client = FakeClient(
                {
                    "mam": (
                        200,
                        MAM_RESPONSE,
                        {"Set-Cookie": "mam_id=rotated-live; Path=/; HttpOnly"},
                    )
                }
            )
            providers = MetadataProviders(
                client,
                FakeCache(),
                mam_id="bootstrap",
                mam_cookie_path=cookie_path,
            )
            providers.mam_search("Red Rising", "Pierce Brown")
            self.assertEqual(providers.mam_id, "rotated-live")
            self.assertEqual(cookie_path.read_text(encoding="utf-8"), "rotated-live")
            self.assertEqual(client.calls[0]["headers"]["Cookie"], "mam_id=bootstrap")

            providers.mam_search("Golden Son", "Pierce Brown")
            self.assertEqual(client.calls[1]["headers"]["Cookie"], "mam_id=rotated-live")

    def test_unchanged_set_cookie_does_not_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "mam.cookies"
            cookie_path.write_text("same", encoding="utf-8")
            client = FakeClient(
                {"mam": (200, MAM_RESPONSE, {"Set-Cookie": "mam_id=same; Path=/"})}
            )
            providers = MetadataProviders(
                client,
                FakeCache(),
                mam_id="same",
                mam_cookie_path=cookie_path,
            )
            providers.mam_search("Red Rising", "Pierce Brown")
            self.assertEqual(providers.mam_id, "same")
            self.assertEqual(cookie_path.read_text(encoding="utf-8"), "same")


if __name__ == "__main__":
    unittest.main()
