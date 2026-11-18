from __future__ import annotations

import os
from pathlib import Path


def books_root() -> Path:
    env = os.environ.get("BOOKS_ROOT")
    if env:
        return Path(env)
    return Path("/data/Dropbox/Books")


def audiobooks_root() -> Path:
    env = os.environ.get("AUDIOBOOKS_ROOT")
    if env:
        return Path(env)
    return Path("/data/Audiobooks")


def staging_config_root() -> Path:
    env = os.environ.get("STAGING_CONFIG_ROOT") or os.environ.get("STAGER_CONFIG_ROOT")
    if env:
        return Path(env)
    return Path("/config")
