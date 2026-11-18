from __future__ import annotations

from typing import Any

from stager_core.discovery import FlatBook, enrich_flatten_base, sanitize_folder_name, stem_base
from stager_core.metadata.types import ManualHints, TagInfo


def build_search_context(
    book: FlatBook,
    tags: TagInfo,
    manual: ManualHints | None = None,
) -> dict[str, Any]:
    filenames = [f.name for f in book.files]
    folder_title = book.flatten_name
    file_stem = stem_base(book.files[0].name.rsplit(".", 1)[0]) if book.files else ""

    manual_author = (manual.author or "").strip() if manual else ""
    manual_title = (manual.title or "").strip() if manual else ""

    title_hints: list[str] = []
    if manual_title:
        title_hints.append(manual_title)
    else:
        title_hints.extend(
            [
                tags.title,
                tags.album,
                folder_title,
                file_stem,
                sanitize_folder_name(book.parent_context) if book.parent_context else "",
            ]
        )

    author_hints: list[str] = []
    if manual_author:
        author_hints.append(manual_author)
    else:
        author_hints.extend(
            [
                tags.artist,
                tags.albumartist,
            ]
        )
        for part in reversed(book.source_path_parts):
            if part and part not in {"Audiobooks", "audiobooks"}:
                author_hints.append(part)

    title = next((t.strip() for t in title_hints if t and t.strip()), folder_title)
    author = next((a.strip() for a in author_hints if a and a.strip()), "")

    enriched_title = enrich_flatten_base(sanitize_folder_name(title), book.source_path_parts, filenames)

    manual_used = bool(manual_author or manual_title)

    return {
        "title": enriched_title,
        "author": sanitize_folder_name(author) if author else "",
        "asin": tags.asin.upper() if tags.asin else "",
        "folder_title": folder_title,
        "source_path": book.source_path,
        "manual_used": manual_used,
    }
