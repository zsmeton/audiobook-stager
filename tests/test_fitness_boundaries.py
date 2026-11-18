"""Lock import and call boundaries by scanning source. No network."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = (
    ROOT / "stager_core",
    ROOT / "app",
)

# No stager_core module may import app. library_cache's allowlist is empty.
APP_IMPORT_ALLOWLIST: frozenset[str] = frozenset()

# Provider HTTP may live here. The socket client is ratelimit.py today.
HTTP_ALLOWLIST = frozenset(
    {
        "stager_core/metadata/providers.py",
        "stager_core/metadata/ratelimit.py",
    }
)

# os.link, os.unlink, and Path.unlink. Reads, writes, mkdir, and rmdir are not scanned.
LINK_ALLOWLIST = frozenset({"stager_core/staging.py"})

_HTTP_CLIENT_ROOTS = ("requests", "httpx", "urllib.request", "http.client")
_HTTP_CALL_TAILS = frozenset(
    {"urlopen", "urlretrieve", "HTTPConnection", "HTTPSConnection"}
)
_DYNAMIC_IMPORTS = frozenset({"__import__", "importlib.import_module"})


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _python_files(base: Path) -> list[Path]:
    return sorted(
        path
        for path in base.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dynamic_import_target(node: ast.Call) -> str | None:
    name = _dotted_name(node.func)
    if name in _DYNAMIC_IMPORTS and node.args:
        return _const_str(node.args[0])
    return None


def _is_app_module(module: str) -> bool:
    return module == "app" or module.startswith("app.")


def _imports_app(path: Path) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_app_module(alias.name):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module and _is_app_module(module):
                hits.append(module)
        elif isinstance(node, ast.Call):
            target = _dynamic_import_target(node)
            if target and _is_app_module(target):
                hits.append(target)
    return hits


def _is_http_client_module(module: str) -> bool:
    return any(
        module == root or module.startswith(root + ".") for root in _HTTP_CLIENT_ROOTS
    )


def _http_call_label(func: ast.AST) -> str | None:
    dotted = _dotted_name(func)
    if not dotted or "." not in dotted:
        return None
    tail = dotted.rsplit(".", 1)[-1]
    if tail in _HTTP_CALL_TAILS:
        return dotted
    if dotted == "urllib.request.Request":
        return dotted
    root = dotted.split(".", 1)[0]
    if root in {"requests", "httpx"}:
        return dotted
    return None


def _http_client_uses(path: Path) -> list[str]:
    """Imports and calls that open HTTP.

    urllib.parse (quote, urlencode, unquote) is URL text, not a client call.
    """
    hits: list[str] = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_http_client_module(alias.name):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "urllib":
                for alias in node.names:
                    if alias.name == "request":
                        hits.append("from urllib import request")
            elif module == "http":
                for alias in node.names:
                    if alias.name == "client":
                        hits.append("from http import client")
            elif _is_http_client_module(module):
                names = ", ".join(alias.name for alias in node.names)
                hits.append(f"from {module} import {names}")
        elif isinstance(node, ast.Call):
            label = _http_call_label(node.func)
            if label:
                hits.append(f"call {label}:{node.lineno}")
                continue
            target = _dynamic_import_target(node)
            if target and _is_http_client_module(target):
                hits.append(f"import {target}:{node.lineno}")
    return hits


def _assigned_os_names(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    os_names: set[str] = set()
    link_names: set[str] = set()
    unlink_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_names.add(alias.asname or "os")
                elif alias.name.startswith("os.") and not alias.asname:
                    os_names.add("os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name == "link":
                    link_names.add(bound)
                elif alias.name == "unlink":
                    unlink_names.add(bound)
    return os_names, link_names, unlink_names


def _link_unlink_calls(path: Path) -> list[str]:
    """os.link, os.unlink, and pathlib Path.unlink calls.

    Path.unlink is any ``.unlink()`` call other than ``os.unlink``, including
    ``path.unlink()`` and ``dst.unlink()``.
    """
    tree = _parse(path)
    os_names, link_names, unlink_names = _assigned_os_names(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in link_names:
                hits.append(f"os.link:{node.lineno}")
            elif func.id in unlink_names:
                hits.append(f"os.unlink:{node.lineno}")
            continue
        if not isinstance(func, ast.Attribute):
            continue
        receiver_is_os = isinstance(func.value, ast.Name) and func.value.id in os_names
        if func.attr == "link" and receiver_is_os:
            hits.append(f"os.link:{node.lineno}")
        elif func.attr == "unlink" and receiver_is_os:
            hits.append(f"os.unlink:{node.lineno}")
        elif func.attr == "unlink":
            hits.append(f"Path.unlink:{node.lineno}")
    return hits


def _hits_by_file(scanner, bases: tuple[Path, ...]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for base in bases:
        for path in _python_files(base):
            hits = scanner(path)
            if hits:
                found[_rel(path)] = hits
    return found


def _format_hits(found: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for rel in sorted(found):
        for hit in found[rel]:
            lines.append(f"{rel}: {hit}")
    return "\n".join(lines)


def test_stager_core_imports_app_only_from_library_cache():
    """No stager_core module imports app.

    library_cache used to lazily import ``app.api.holder``. That allowlist is
    empty. Any stager_core module that imports app fails.
    """
    found = _hits_by_file(_imports_app, (ROOT / "stager_core",))
    assert set(found) == APP_IMPORT_ALLOWLIST, _format_hits(found)
    assert not found


def test_provider_http_stays_in_providers_and_ratelimit():
    """Provider HTTP stays in the provider module and the rate limiter.

    Allowed homes:
    - stager_core/metadata/providers.py
    - stager_core/metadata/ratelimit.py

    Today the HTTP client is only in ratelimit.py: ``import urllib.request``,
    ``urllib.request.Request``, and ``urllib.request.urlopen``. providers.py
    builds URLs with urllib.parse and calls RateLimitedClient.request_json.
    It does not import requests, httpx, or urllib.request. lookup.py does not
    either. app/api.py imports urllib.parse.unquote, which is not an HTTP call.
    No other module under stager_core/ or app/ is allowlisted.
    """
    found = _hits_by_file(_http_client_uses, SCAN_DIRS)
    outside = set(found) - HTTP_ALLOWLIST
    assert not outside, _format_hits(found)
    rate_hits = found.get("stager_core/metadata/ratelimit.py", [])
    assert any("urllib.request" in hit for hit in rate_hits), _format_hits(found)
    assert any("urlopen" in hit for hit in rate_hits), _format_hits(found)


def test_link_and_unlink_stay_in_staging():
    """os.link, os.unlink, and Path.unlink stay in stager_core/staging.py.

    Today staging.py calls os.link and Path.unlink (path.unlink, dst.unlink).
    No os.unlink call exists under stager_core/ or app/. No other file is
    allowlisted. Ordinary reads, writes, mkdir, and rmdir are not this rule.
    """
    found = _hits_by_file(_link_unlink_calls, SCAN_DIRS)
    assert set(found) == LINK_ALLOWLIST, _format_hits(found)
    kinds = {hit.split(":", 1)[0] for hit in found["stager_core/staging.py"]}
    assert {"os.link", "Path.unlink"} <= kinds, _format_hits(found)
