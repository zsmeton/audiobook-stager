"""Playwright e2e harness: temp books/library/config + uvicorn."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from pathlib import Path

import httpx
import pytest

from tests.e2e import fixtures_fs
from tests.e2e.helpers import dismiss_bootstrap_and_scan

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_healthy(base_url: str, *, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/api/health", timeout=2.0)
            if resp.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.2)
    raise RuntimeError(f"server not healthy at {base_url}: {last_err}")


@pytest.fixture
def e2e_env(tmp_path: Path, request: pytest.FixtureRequest) -> Generator[dict, None, None]:
    """Prepare isolated roots. Use ``@pytest.mark.e2e_layout('happy_scan')`` etc."""
    books = tmp_path / "books"
    library = tmp_path / "library"
    config = tmp_path / "config"
    books.mkdir()
    library.mkdir()
    config.mkdir()

    marker = request.node.get_closest_marker("e2e_layout")
    layout_name = marker.args[0] if marker and marker.args else "smoke"
    layout_fn: Callable[[Path, Path], None] = getattr(fixtures_fs, f"layout_{layout_name}")
    layout_fn(books, library)

    env = {
        "BOOKS_ROOT": str(books),
        "AUDIOBOOKS_ROOT": str(library),
        "STAGING_CONFIG_ROOT": str(config),
        "STAGER_METADATA_BACKEND": "fixture",
        "AUDNEXUS_MIN_INTERVAL_MS": "0",
        "OPENLIBRARY_MIN_INTERVAL_MS": "0",
        "MAM_REQUESTS_PER_MINUTE": "10000",
        "GOOGLE_BOOKS_API_KEY": "fixture-key",
        "STAGER_MAM_ID": "fixture-mam-id",
        "METADATA_CONTACT_EMAIL": "e2e@example.com",
    }
    delay_marker = request.node.get_closest_marker("e2e_fixture_delay_ms")
    if delay_marker and delay_marker.args:
        env["STAGER_FIXTURE_LOOKUP_DELAY_MS"] = str(int(delay_marker.args[0]))
    yield {
        "books_root": books,
        "library_root": library,
        "config_root": config,
        "env": env,
        "layout": layout_name,
    }


@pytest.fixture
def stager_server(e2e_env: dict) -> Generator[dict, None, None]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(e2e_env["env"])
    # Ensure imports resolve the same way as conftest.
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT),
            env.get("PYTHONPATH", ""),
        ]
    )

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_healthy(base_url)
        yield {
            **e2e_env,
            "base_url": base_url,
            "port": port,
            "proc": proc,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture
def scanned_page(page, stager_server: dict):
    """Browser page after a completed scan for the fixture layout."""
    dismiss_bootstrap_and_scan(page, stager_server["base_url"])
    page.goto(stager_server["base_url"] + "/")
    page.wait_for_load_state("domcontentloaded")
    # Wait for either staging rows, conflicts, or explicit empty state (visible).
    page.locator(
        "#booksList .book-item[data-book-id], "
        "#conflictsList .book-item[data-target-key], "
        "#stagingEmpty:not(.hidden), "
        "#conflictsEmpty:not(.hidden)"
    ).first.wait_for(state="visible", timeout=60_000)
    return page
