"""Pytest path setup.

``stager_core`` and the FastAPI ``app`` package both live at the repo root.
Put that root on ``sys.path`` so the suite runs with a bare ``pytest`` invocation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_s = str(_ROOT)
if _s not in sys.path:
    sys.path.insert(0, _s)
