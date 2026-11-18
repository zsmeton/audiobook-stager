"""Media-kind seam.

Discovery and tag reading ask this module for a kind before they keep or open
a file. Only audiobook is implemented, so a later format can be registered
beside it without an audio-only call chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

AUDIOBOOK = "audiobook"

_AUDIOBOOK_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".mp4",
        ".m4a",
        ".m4b",
        ".flac",
        ".ogg",
        ".opus",
        ".wav",
        ".aac",
        ".wma",
    }
)


class UnknownMediaKind(LookupError):
    """The named kind is not implemented. No file is opened or parsed."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"media kind is not implemented: {kind}")


class MediaKind(Protocol):
    """What discovery and tag reading call.

    Ebook formats (epub, mobi) are not a kind. They have no parser and no
    file reader here.
    """

    name: str

    def extensions(self) -> frozenset[str]:
        """Suffixes this kind claims."""

    def matches(self, path: Path) -> bool:
        """True when ``path`` is a file of this kind."""

    def read_tags(self, path: Path):
        """Read tags for a file of this kind."""


class _AudiobookKind:
    name = AUDIOBOOK

    def extensions(self) -> frozenset[str]:
        return _AUDIOBOOK_EXTENSIONS

    def matches(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in _AUDIOBOOK_EXTENSIONS

    def read_tags(self, path: Path):
        from stager_core.metadata.tags import read_audiobook_tags

        return read_audiobook_tags(path)


# Ebook formats (epub, mobi) are not registered. No parser. No file reader.
_KINDS: dict[str, MediaKind] = {
    AUDIOBOOK: _AudiobookKind(),
}


def implemented_kinds() -> tuple[str, ...]:
    """Kind names this process can discover and tag."""
    return tuple(_KINDS)


def get_kind(name: str) -> MediaKind:
    """Return an implemented kind.

    Ebook formats (epub, mobi) are a comment on this interface, not a parser
    and not a file reader. Asking for one raises ``UnknownMediaKind`` and does
    not open a file.
    """
    try:
        return _KINDS[name]
    except KeyError:
        raise UnknownMediaKind(name) from None
