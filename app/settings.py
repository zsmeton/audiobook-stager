from __future__ import annotations

import os
from pathlib import Path

import stager_core.paths as path_roots


def books_root() -> Path:
    env = os.environ.get("BOOKS_ROOT")
    if env:
        return Path(env)
    return Path("./data/seeds")


def audiobooks_root() -> Path:
    env = os.environ.get("AUDIOBOOKS_ROOT")
    if env:
        return Path(env)
    return Path("./data/library")


def staging_config_root() -> Path:
    env = os.environ.get("STAGING_CONFIG_ROOT") or os.environ.get("STAGER_CONFIG_ROOT")
    if env:
        return Path(env)
    return Path("/config")


def config_root() -> Path:
    return staging_config_root()


def db_path() -> Path:
    root = config_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "stager.db"


def books_path() -> Path:
    return books_root()


def library_path() -> Path:
    return audiobooks_root()


path_roots.bind_path_resolvers(
    books=books_root,
    audiobooks=audiobooks_root,
    config=staging_config_root,
)
