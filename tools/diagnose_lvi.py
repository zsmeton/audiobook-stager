#!/usr/bin/env python3
"""Diagnose LVI chrome for a book: MAM candidates + manual banner signals.

Run inside the audiobook-stager container:

    python tools/diagnose_lvi.py
    python tools/diagnose_lvi.py --book-id 05ad27951856
    python tools/diagnose_lvi.py --title "Dark Forest"
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.library_vocab import (
    LibraryVocabulary,
    author_key,
    series_key,
)
from stager_core.metadata.lvi import (
    annotate_candidates_lvi,
    build_lvi_from_db,
    local_signals,
    resolve_lvi_form_match,
    series_hints,
)
from stager_core.metadata.normalize import provider_text
from stager_core.metadata.types import MetadataCandidate, TagInfo


def _db_path() -> Path:
    root = os.environ.get("STAGER_CONFIG_ROOT") or os.environ.get("STAGING_CONFIG_ROOT") or "/config"
    return Path(root) / "stager.db"


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _flat_book_from_row(row: sqlite3.Row) -> FlatBook:
    files = json.loads(row["files_json"] or "[]")
    return FlatBook(
        id=row["id"],
        source_path=row["source_path"] or "",
        source_path_parts=json.loads(row["source_path_parts"] or "[]"),
        top_level_pack=row["top_level_pack"] or "",
        parent_context=row["parent_context"] or "",
        grouping=row["grouping"] or "",
        flatten_name=row["flatten_name"] or "",
        flatten_target=(row["flatten_target"] if "flatten_target" in row.keys() else "") or "",
        files=[AudioFile(name=f["name"], source=f.get("source", f["name"]), size_bytes=int(f.get("size_bytes") or 0)) for f in files],
    )


def _tags_from_row(row: sqlite3.Row) -> TagInfo:
    raw = json.loads(row["tags_json"] or "{}")
    return TagInfo(
        title=str(raw.get("title") or ""),
        album=str(raw.get("album") or ""),
        artist=str(raw.get("artist") or ""),
        albumartist=str(raw.get("albumartist") or ""),
        asin=str(raw.get("asin") or ""),
        narrator=str(raw.get("narrator") or ""),
        raw=raw.get("raw") if isinstance(raw.get("raw"), dict) else raw,
    )


def _find_book(conn: sqlite3.Connection, *, book_id: str, title: str) -> sqlite3.Row | None:
    if book_id:
        return conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    like = f"%{title}%"
    return conn.execute(
        """
        SELECT * FROM books
        WHERE chosen_title LIKE ? OR source_path LIKE ? OR suggested_title LIKE ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (like, like, like),
    ).fetchone()


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _explain_series_exact(lvi: LibraryVocabulary, author: str, series: str) -> None:
    akey = author_key(provider_text(author))
    stext = provider_text(series)
    skey = series_key(stext)
    print(f"  author_key: {akey!r}")
    print(f"  series (provider_text): {stext!r}")
    print(f"  series_key: {skey!r}")
    by_auth = lvi.series_by_author.get(akey) or {}
    print(f"  LVI series keys for author: {list(by_auth.keys())!r}")
    if skey in by_auth:
        print("  -> EXACT MATCH")
    else:
        print("  -> NO exact match")
        for lk, ent in by_auth.items():
            print(f"     library canonical: {ent.canonical_name!r} (key {lk!r})")


def _candidate_from_dict(c: dict[str, Any]) -> MetadataCandidate:
    return MetadataCandidate(
        author=str(c.get("author") or ""),
        title=str(c.get("title") or ""),
        source=str(c.get("source") or ""),
        confidence=float(c.get("confidence") or 0),
        narrator=str(c.get("narrator") or ""),
        series=str(c.get("series") or ""),
        series_index=str(c.get("series_index") or ""),
        subtitle=str(c.get("subtitle") or ""),
        asin=str(c.get("asin") or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose LVI chrome for a stager.db book")
    parser.add_argument("--db", type=Path, default=None, help="Path to stager.db (default: /config/stager.db)")
    parser.add_argument("--book-id", default="", help="Book id")
    parser.add_argument("--title", default="Dark Forest", help="Title substring when --book-id omitted")
    args = parser.parse_args()

    db = args.db or _db_path()
    if not db.is_file():
        print(f"ERROR: database not found: {db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = _find_book(conn, book_id=args.book_id.strip(), title=args.title.strip())
    if row is None:
        print("ERROR: no matching book", file=sys.stderr)
        return 1

    lvi = build_lvi_from_db(conn)
    row_d = _row_dict(row)
    book = _flat_book_from_row(row)
    tags = _tags_from_row(row)
    signals = local_signals(book, tags)
    lvi_match_stored = json.loads(row_d.get("lvi_match_json") or "{}")
    eff_author = (row_d.get("chosen_author") or row_d.get("suggested_author") or "").strip()
    eff_series = (row_d.get("chosen_series") or row_d.get("suggested_series") or "").strip()
    lvi_form = resolve_lvi_form_match(lvi, eff_author, eff_series)
    candidates = json.loads(row_d.get("candidates_json") or "[]")

    _section(f"BOOK {row['id']} — {row_d.get('chosen_title') or row_d.get('suggested_title')}")
    print(f"  status: {row['status']}")
    print(f"  chosen_author: {row_d.get('chosen_author')!r}")
    print(f"  chosen_title: {row_d.get('chosen_title')!r}")
    print(f"  chosen_series: {row_d.get('chosen_series')!r}")
    print(f"  chosen_series_index: {row_d.get('chosen_series_index')!r}")
    print(f"  suggested_series: {row_d.get('suggested_series')!r}")
    print(f"  suggested_series_index: {row_d.get('suggested_series_index')!r}")

    _section("LVI VOCAB (staged library)")
    print(lvi.summary())
    akey = author_key("Cixin Liu")
    if akey in lvi.authors:
        ent = lvi.authors[akey]
        print(f"  author {ent.canonical_name!r}: {ent.book_count} staged book(s)")
    for sk, sent in (lvi.series_by_author.get(akey) or {}).items():
        print(f"  series {sent.canonical_name!r} key={sk!r} indices={sorted(sent.indices_known)}")

    _section("MANUAL FORM CHROME (lvi_form_match — edit field values)")
    print("  UI: banner + gold Author/Series fields when exact match on staged folders.")
    print(f"  effective_author: {eff_author!r}")
    print(f"  effective_series: {eff_series!r}")
    print(f"  lvi_form_match: {lvi_form.to_dict()}")
    if not lvi_form.author_matched:
        print("  BANNER/FIELDS: hidden — author does not exact-match LVI")
    elif not lvi_form.series_matched:
        print("  BANNER: author only; Series field not gold")
        if eff_series and "#" in eff_series:
            print("  NOTE: '#' in series field prevents exact folder match — use Series # field")
    else:
        print(f"  BANNER: author + series — {lvi_form.author!r} · {lvi_form.series!r}")

    _section("LEGACY lvi_match_json (lookup signals — not shown in UI)")
    print(f"  stored (not used for chrome): {lvi_match_stored}")

    eff_series = (row_d.get("chosen_series") or row_d.get("suggested_series") or "").strip()
    if eff_series:
        _section("MANUAL effective_series vs LVI (exact filesystem key)")
        _explain_series_exact(lvi, row_d.get("chosen_author") or "", eff_series)
        if "#" in eff_series:
            print("  NOTE: chosen/suggested series contains '#' — will NOT match folder name")
            print("        (library folder is series name only; index is separate field)")

    _section("MAM CANDIDATES")
    mam_rows = [c for c in candidates if c.get("source") == "mam"]
    if not mam_rows:
        print("  No MAM candidates in candidates_json — re-run lookup with STAGER_MAM_ID set.")
    for i, raw in enumerate(mam_rows, 1):
        print(f"\n  --- MAM candidate {i} ---")
        print(f"  author: {raw.get('author')!r}")
        print(f"  title: {raw.get('title')!r}")
        print(f"  series: {raw.get('series')!r}")
        print(f"  series_index: {raw.get('series_index')!r}")
        print(f"  stored lvi_author_matched: {raw.get('lvi_author_matched')}")
        print(f"  stored lvi_series_matched: {raw.get('lvi_series_matched')}")
        mc = _candidate_from_dict(raw)
        annotate_candidates_lvi([mc], lvi)
        print(f"  recomputed lvi_author_matched: {mc.lvi_author_matched}")
        print(f"  recomputed lvi_series_matched: {mc.lvi_series_matched}")
        print(f"  recomputed lvi_in_library (author-only pill): {mc.lvi_in_library}")
        print("  series exact check:")
        _explain_series_exact(lvi, mc.author, mc.series)
        print("  UI series line gold: whole line if lvi_series_matched (series field only; # from series_index)")
        if mc.lvi_series_matched:
            parts = [mc.series] if mc.series else []
            if mc.series_index:
                parts.append(f"#{mc.series_index}")
            print(f"  -> would render gold: {' '.join(parts)!r}")
        else:
            reasons = []
            if not mc.lvi_author_matched:
                reasons.append("author does not exact-match LVI")
            elif not provider_text(mc.series).strip():
                reasons.append("empty series on candidate")
            else:
                reasons.append("series string does not exact-match library folder key")
            print(f"  -> NO gold: {'; '.join(reasons)}")

    _section("OTHER CANDIDATES (series chrome)")
    for raw in candidates:
        if raw.get("source") == "mam":
            continue
        src = raw.get("source")
        mc = _candidate_from_dict(raw)
        annotate_candidates_lvi([mc], lvi)
        if not mc.series and not mc.series_index:
            continue
        print(f"  {src}: series={raw.get('series')!r} idx={raw.get('series_index')!r} "
              f"author_hit={mc.lvi_author_matched} series_hit={mc.lvi_series_matched}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
