"""Filesystem builders for Audiobook Stager e2e fixtures."""

from __future__ import annotations

import base64
from pathlib import Path

from mutagen import File as MutagenFile

# Tiny silent MP3 (ffmpeg anullsrc 0.05s) so mutagen can read/write tags.
_SILENT_MP3 = base64.b64decode(
    "SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjYyLjEyLjEwMQAAAAAAAAAAAAAA//tAwAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAADAAAB7gCUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJTKysrKysrKysrKysrKysrKysrKysrKysrKysrKysrKysr///////////////////////////////////////////8AAAAATGF2YzYyLjI4AAAAAAAAAAAAAAAAJAKjAAAAAAAAAe4nWnczAAAAAAD/+xDEAAPAAAGkAAAAIAAANIAAAARMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7EMQpg8AAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//sQxFMDwAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVU="
)


def write_tagged_audio(
    path: Path,
    *,
    title: str = "",
    artist: str = "",
    album: str = "",
    payload: bytes | None = None,
) -> Path:
    """Write a tiny valid MP3 with EasyID3-compatible tags."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _SILENT_MP3 if payload is None else (_SILENT_MP3 + payload)
    path.write_bytes(raw)
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise RuntimeError(f"mutagen could not open {path}")
    if audio.tags is None:
        audio.add_tags()
    if title:
        audio["title"] = [title]
    if artist:
        audio["artist"] = [artist]
    if album or title:
        audio["album"] = [album or title]
    audio.save()
    return path


def seed_book(
    books_root: Path,
    *,
    rel_dir: str,
    filename: str = "book.mp3",
    title: str = "",
    artist: str = "",
    album: str = "",
    payload: bytes | None = None,
) -> Path:
    return write_tagged_audio(
        books_root / Path(rel_dir) / filename,
        title=title or Path(filename).stem,
        artist=artist,
        album=album or title or Path(filename).stem,
        payload=payload,
    )


def library_book(
    library_root: Path,
    *,
    rel_dir: str,
    filename: str = "book.mp3",
    title: str = "",
    artist: str = "",
    album: str = "",
    payload: bytes | None = None,
) -> Path:
    return write_tagged_audio(
        library_root / Path(rel_dir) / filename,
        title=title,
        artist=artist,
        album=album,
        payload=payload,
    )


def layout_smoke(books_root: Path, library_root: Path) -> None:
    books_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)


def layout_happy_scan(books_root: Path, library_root: Path) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    seed_book(
        books_root,
        rel_dir="Pierce Brown/Red Rising",
        title="Red Rising",
        artist="Pierce Brown",
        payload=b"RR",
    )
    seed_book(
        books_root,
        rel_dir="Andy Weir/Project Hail Mary",
        title="Project Hail Mary",
        artist="Andy Weir",
        payload=b"PHM",
    )
    seed_book(
        books_root,
        rel_dir="Pierce Brown/Golden Son",
        title="Golden Son",
        artist="Pierce Brown",
        payload=b"GS",
    )


def layout_conflict_pending(books_root: Path, library_root: Path) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    seed_book(
        books_root,
        rel_dir="dup-a/Conflict Author/Shared Title",
        filename="copy-a.mp3",
        title="Shared Title",
        artist="Conflict Author",
        payload=b"A",
    )
    seed_book(
        books_root,
        rel_dir="dup-b/Conflict Author/Shared Title",
        filename="copy-b.mp3",
        title="Shared Title",
        artist="Conflict Author",
        payload=b"B",
    )


def layout_conflict_staged(books_root: Path, library_root: Path) -> None:
    library_book(
        library_root,
        rel_dir="Conflict Author/Shared Title",
        filename="existing.mp3",
        title="Shared Title",
        artist="Conflict Author",
        payload=b"L",
    )
    seed_book(
        books_root,
        rel_dir="incoming/Shared Title",
        filename="incoming.mp3",
        title="Shared Title",
        artist="Conflict Author",
        payload=b"S",
    )


def layout_merge_parts(books_root: Path, library_root: Path) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    seed_book(
        books_root,
        rel_dir="Merge Author/Split Book part1",
        filename="part1.mp3",
        title="Split Book",
        artist="Merge Author",
        payload=b"1",
    )
    seed_book(
        books_root,
        rel_dir="Merge Author/Split Book part2",
        filename="part2.mp3",
        title="Split Book",
        artist="Merge Author",
        payload=b"2",
    )


def layout_lvi(books_root: Path, library_root: Path) -> None:
    """Canonical + messy seeds; library starts empty so approve can seed LVI."""
    library_root.mkdir(parents=True, exist_ok=True)
    seed_book(
        books_root,
        rel_dir="Cixin Liu/The Three-Body Problem",
        title="The Three-Body Problem",
        artist="Cixin Liu",
        payload=b"S1",
    )
    seed_book(
        books_root,
        rel_dir="Cixin/The Dark Forest",
        title="The Dark Forest",
        artist="Cixin",
        payload=b"S2",
    )
