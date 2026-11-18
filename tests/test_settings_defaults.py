"""Unset path defaults and the public config example. No network."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from app.settings import (
    audiobooks_root,
    books_path,
    books_root,
    library_path,
    staging_config_root,
)
from stager_core.paths import audiobooks_root as paths_library_root
from stager_core.paths import books_root as paths_books_root
from stager_core.paths import staging_config_root as paths_config_root

ROOT = Path(__file__).resolve().parents[1]

_PATH_ENV = (
    "BOOKS_ROOT",
    "AUDIOBOOKS_ROOT",
    "STAGING_CONFIG_ROOT",
    "STAGER_CONFIG_ROOT",
)

_EXAMPLE_KEYS = (
    "DATA_ROOT",
    "STAGER_CONFIG_HOST",
    "AUDIOBOOK_STAGER_PORT",
    "TZ",
    "BOOKS_ROOT",
    "AUDIOBOOKS_ROOT",
    "STAGER_CONFIG_ROOT",
    "STAGING_CONFIG_ROOT",
    "GOOGLE_BOOKS_API_KEY",
    "METADATA_CONTACT_EMAIL",
    "AUDNEXUS_MIN_INTERVAL_MS",
    "OPENLIBRARY_MIN_INTERVAL_MS",
    "AUDNEXUS_REGION",
    "STAGER_MAM_ID",
    "MAM_ID",
    "MAM_REQUESTS_PER_MINUTE",
    "STAGER_MAM_COOKIE_FILE",
    "MAM_COOKIE_FILE",
    "CONFIG_ROOT",
    "STAGER_METADATA_BACKEND",
    "STAGER_METADATA_FIXTURES",
    "STAGER_FIXTURE_LOOKUP_DELAY_MS",
    "SCAN_FINGERPRINT_WORKERS",
)


def _assignments(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            continue
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _comment_above(text: str, key: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            comments: list[str] = []
            cursor = index - 1
            while cursor >= 0:
                previous = lines[cursor].strip()
                if not previous:
                    cursor -= 1
                    continue
                if previous.startswith("#"):
                    comments.append(previous.lstrip("#").strip())
                    cursor -= 1
                    continue
                break
            return " ".join(reversed(comments))
    raise AssertionError(f"{key} missing")


class SettingsDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in _PATH_ENV}
        for key in _PATH_ENV:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_unset_books_root_is_data_seeds(self) -> None:
        self.assertEqual(books_root(), Path("./data/seeds"))
        self.assertEqual(books_path(), Path("./data/seeds"))
        self.assertEqual(paths_books_root(), Path("./data/seeds"))
        self.assertFalse(books_root().is_absolute())

    def test_unset_library_root_is_data_library(self) -> None:
        self.assertEqual(audiobooks_root(), Path("./data/library"))
        self.assertEqual(library_path(), Path("./data/library"))
        self.assertEqual(paths_library_root(), Path("./data/library"))
        self.assertFalse(audiobooks_root().is_absolute())

    def test_blank_path_env_uses_the_unset_default(self) -> None:
        os.environ["BOOKS_ROOT"] = ""
        os.environ["AUDIOBOOKS_ROOT"] = ""
        self.assertEqual(books_root(), Path("./data/seeds"))
        self.assertEqual(paths_library_root(), Path("./data/library"))

    def test_set_path_env_is_honored(self) -> None:
        os.environ["BOOKS_ROOT"] = "/tmp/seeds"
        os.environ["AUDIOBOOKS_ROOT"] = "/tmp/library"
        self.assertEqual(books_root(), Path("/tmp/seeds"))
        self.assertEqual(paths_books_root(), Path("/tmp/seeds"))
        self.assertEqual(audiobooks_root(), Path("/tmp/library"))
        self.assertEqual(paths_library_root(), Path("/tmp/library"))

    def test_unset_config_root_stays_config(self) -> None:
        self.assertEqual(staging_config_root(), Path("/config"))
        self.assertEqual(paths_config_root(), Path("/config"))

    def test_staging_config_root_overrides_stager_config_root(self) -> None:
        os.environ["STAGER_CONFIG_ROOT"] = "/from-stager"
        os.environ["STAGING_CONFIG_ROOT"] = "/from-staging"
        self.assertEqual(staging_config_root(), Path("/from-staging"))
        self.assertEqual(paths_config_root(), Path("/from-staging"))


class PublicConfigExampleTests(unittest.TestCase):
    def test_env_example_lists_every_read_variable(self) -> None:
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        values = _assignments(text)
        self.assertEqual(list(values), list(_EXAMPLE_KEYS))
        self.assertEqual(values["TZ"], "UTC")
        self.assertEqual(values["DATA_ROOT"], "./data")
        self.assertEqual(values["BOOKS_ROOT"], "/data/seeds")
        self.assertEqual(values["AUDIOBOOKS_ROOT"], "/data/library")
        self.assertIn("./data/seeds", text)
        self.assertIn("./data/library", text)
        for key in ("GOOGLE_BOOKS_API_KEY", "STAGER_MAM_ID", "MAM_ID"):
            self.assertEqual(values[key], "")
            self.assertIn("optional", _comment_above(text, key).lower())
        self.assertEqual(values["METADATA_CONTACT_EMAIL"], "")
        self.assertIn("does not gate Open Library", _comment_above(text, "METADATA_CONTACT_EMAIL"))
        self.assertNotIn("America/Denver", text)
        self.assertNotIn("Dropbox/Books", text)
        self.assertNotIn("/data/Audiobooks", text)

    def test_compose_defaults_are_utc_and_data_mount(self) -> None:
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("TZ: ${TZ:-UTC}", text)
        self.assertIn("BOOKS_ROOT: ${BOOKS_ROOT:-/data/seeds}", text)
        self.assertIn("AUDIOBOOKS_ROOT: ${AUDIOBOOKS_ROOT:-/data/library}", text)
        self.assertIn("./data/seeds", text)
        self.assertIn("./data/library", text)
        self.assertIn("container_name: audiobook-stager", text)
        self.assertEqual(text.count("container_name:"), 1)
        self.assertNotIn("America/Denver", text)
        self.assertNotIn("Dropbox/Books", text)
        self.assertNotIn("/data/Audiobooks", text)

    def test_dockerfile_has_no_personal_timezone(self) -> None:
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("America/Denver", text)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("ENV ") and "TZ" in stripped.split():
                self.assertIn("UTC", stripped)


if __name__ == "__main__":
    unittest.main()
