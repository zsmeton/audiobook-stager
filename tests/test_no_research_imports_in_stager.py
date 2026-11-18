"""Ensure stager production code never imports research modules."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = (
    ROOT / "stager_core",
    ROOT / "app",
)


def _imports_research(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "research" or alias.name.startswith("research."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "research" or node.module.startswith("research.")):
                hits.append(node.module)
    return hits


def test_no_research_imports_in_stager():
    violations: list[str] = []
    for base in SCAN_DIRS:
        for path in base.rglob("*.py"):
            for mod in _imports_research(path):
                violations.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not violations, "\n".join(violations)
