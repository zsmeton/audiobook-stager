from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

ALGO_VERSION = 1

_CHUNK = 1024 * 1024
_SMALL_FILE = 2 * 1024 * 1024


class FingerprintCache(Protocol):
    def get(self, rel_path: str, size_bytes: int, mtime_ns: int) -> str | None: ...

    def put(self, rel_path: str, size_bytes: int, mtime_ns: int, fingerprint: str) -> None: ...

    def flush(self) -> None: ...


def _hash_payload(size: int, head: bytes, tail: bytes) -> str:
    payload = f"{size}|".encode() + head + b"|" + tail
    return hashlib.sha256(payload, usedforsecurity=False).hexdigest()


def _read_fingerprint_bytes(path: Path, size: int) -> str:
    with path.open("rb") as f:
        if size < _SMALL_FILE:
            head = f.read()
            tail = head
        else:
            head = f.read(_CHUNK)
            f.seek(max(0, size - _CHUNK))
            tail = f.read(_CHUNK)
    return _hash_payload(size, head, tail)


def file_fingerprint(
    path: Path,
    *,
    stat_result: os.stat_result | None = None,
    cache: FingerprintCache | None = None,
    rel_path: str | None = None,
) -> str:
    st = stat_result or path.stat()
    size = st.st_size
    mtime_ns = st.st_mtime_ns

    if cache is not None and rel_path is not None:
        cached = cache.get(rel_path, size, mtime_ns)
        if cached is not None:
            return cached

    fingerprint = _read_fingerprint_bytes(path, size)

    if cache is not None and rel_path is not None:
        cache.put(rel_path, size, mtime_ns, fingerprint)

    return fingerprint


def book_id_from_fingerprints(fingerprints: list[str]) -> str:
    return hashlib.sha1(
        "|".join(sorted(fingerprints)).encode(),
        usedforsecurity=False,
    ).hexdigest()[:12]


def book_id_from_paths(
    paths: list[Path],
    *,
    cache: FingerprintCache | None = None,
    books_root: Path | None = None,
    stats: dict[Path, os.stat_result] | None = None,
) -> str:
    fingerprints: list[str] = []
    for path in paths:
        rel_path: str | None = None
        if cache is not None and books_root is not None:
            rel_path = str(path.relative_to(books_root)).replace("\\", "/")
        st = stats.get(path) if stats else None
        fingerprints.append(
            file_fingerprint(
                path,
                stat_result=st,
                cache=cache,
                rel_path=rel_path,
            )
        )
    return book_id_from_fingerprints(fingerprints)
