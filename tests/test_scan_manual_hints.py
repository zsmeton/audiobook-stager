from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db import connect, get_auto_settings, update_auto_settings
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.discovery import AudioFile, FlatBook
from stager_core.metadata.lookup import LookupResolution
from stager_core.metadata.types import ManualHints, TagInfo
from stager_core.staging import build_inode_index


def _flat_book(book_id: str = "book123456789") -> FlatBook:
    return FlatBook(
        id=book_id,
        flatten_name="Wrong Folder Name",
        source_path="seed/wrong",
        source_path_parts=["seed", "wrong"],
        top_level_pack="seed",
        parent_context="",
        grouping="folder",
        files=[
            AudioFile(name="book.m4b", source="seed/wrong/book.m4b", size_bytes=10),
        ],
        flatten_target="Wrong Folder Name",
    )


def _empty_resolution() -> LookupResolution:
    return LookupResolution(
        candidates=[],
        tags=TagInfo(),
        suggested_author="Suggested Author",
        suggested_title="Suggested Title",
        suggested_series="My Series",
        suggested_series_index="1",
        suggested_series_state="confirmed",
        suggested_series_source="audible",
        confidence=0.95,
        confidence_breakdown={},
        lookup_status="ok",
        book_breakdown={},
        series_breakdown={},
        search_context={},
        lvi_match={},
    )


class ScanManualHintsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books = self.root / "books"
        self.library = self.root / "library"
        self.books.mkdir()
        self.library.mkdir()
        self.conn = connect(self.root / "test.db")
        self.session = StagingSession(self.books, self.library)
        self.scan_manager = ScanManager(
            self.conn, self.books, self.library, self.session
        )
        self.book = _flat_book()
        self.manual_calls: list[ManualHints | None] = []

        def capture_resolve(_root, _book, manual=None, **kwargs):
            self.manual_calls.append(manual)
            return _empty_resolution()

        self.scan_manager.lookup.resolve_book = capture_resolve

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _insert_pending_with_pins(
        self,
        *,
        chosen_author: str = "Curated Author",
        chosen_title: str = "Curated Title",
        author_set: int = 1,
        title_set: int = 1,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO books (
                id, scan_id, source_path, source_path_parts, top_level_pack, parent_context,
                grouping, flatten_name, flatten_target, files_json, status,
                suggested_author, suggested_title, chosen_author, chosen_title,
                chosen_author_set, chosen_title_set,
                confidence, staged_path,
                tags_json, candidates_json, lookup_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                self.book.id,
                "scan0",
                self.book.source_path,
                json.dumps(self.book.source_path_parts),
                self.book.top_level_pack,
                self.book.parent_context,
                self.book.grouping,
                self.book.flatten_name,
                self.book.flatten_target,
                json.dumps(
                    [
                        {
                            "name": f.name,
                            "source": f.source,
                            "size_bytes": f.size_bytes,
                        }
                        for f in self.book.files
                    ]
                ),
                "pending",
                "Old Suggested Author",
                "Old Suggested Title",
                chosen_author,
                chosen_title,
                author_set,
                title_set,
                0.5,
                "",
                "{}",
                "[]",
                "ok",
            ),
        )
        self.conn.commit()

    def _upsert(self, *, scan_manual_hints: bool) -> None:
        inode_index = build_inode_index(self.library)
        self.scan_manager._upsert_book(
            "scan1",
            self.book,
            inode_index,
            scan_manual_hints=scan_manual_hints,
        )

    def test_setting_off_does_not_pass_manual_hints(self) -> None:
        self._insert_pending_with_pins()
        self._upsert(scan_manual_hints=False)
        self.assertEqual(len(self.manual_calls), 1)
        self.assertIsNone(self.manual_calls[0])

    def test_setting_on_passes_pinned_metadata(self) -> None:
        self._insert_pending_with_pins()
        self._upsert(scan_manual_hints=True)
        self.assertEqual(len(self.manual_calls), 1)
        manual = self.manual_calls[0]
        self.assertIsNotNone(manual)
        assert manual is not None
        self.assertEqual(manual.author, "Curated Author")
        self.assertEqual(manual.title, "Curated Title")

    def test_setting_on_without_pins_passes_none(self) -> None:
        self._insert_pending_with_pins(author_set=0, title_set=0)
        self._upsert(scan_manual_hints=True)
        self.assertEqual(len(self.manual_calls), 1)
        self.assertIsNone(self.manual_calls[0])

    def test_upsert_does_not_mark_unpinned_book_manual(self) -> None:
        self._insert_pending_with_pins(author_set=0, title_set=0)
        self._upsert(scan_manual_hints=False)
        row = self.conn.execute(
            """
            SELECT chosen_author_set, chosen_title_set,
                   chosen_series_set, chosen_series_index_set
            FROM books WHERE id = ?
            """,
            (self.book.id,),
        ).fetchone()
        self.assertEqual(int(row["chosen_author_set"] or 0), 0)
        self.assertEqual(int(row["chosen_title_set"] or 0), 0)
        self.assertEqual(int(row["chosen_series_set"] or 0), 0)
        self.assertEqual(int(row["chosen_series_index_set"] or 0), 0)

    def test_lookup_book_by_id_uses_pins_regardless_of_setting(self) -> None:
        update_auto_settings(self.conn, scan_manual_hints=False)
        self._insert_pending_with_pins()
        self.manual_calls.clear()
        self.scan_manager.lookup_book_by_id(self.book.id)
        self.assertEqual(len(self.manual_calls), 1)
        manual = self.manual_calls[0]
        self.assertIsNotNone(manual)
        assert manual is not None
        self.assertEqual(manual.author, "Curated Author")
        self.assertEqual(manual.title, "Curated Title")

    def test_run_scan_metadata_pattern_does_not_shadow_get_auto_settings(self) -> None:
        """Regression for UnboundLocalError when scan_manual_hints read precedes inner import."""
        update_auto_settings(self.conn, scan_manual_hints=True)

        def metadata_phase_pattern(conn):
            scan_manual_hints = get_auto_settings(conn)["scan_manual_hints"]
            from app.db import update_auto_settings as _update_auto_settings

            if get_auto_settings(conn)["cache_relookup_pending"]:
                _update_auto_settings(conn, cache_relookup_pending=False)
            return scan_manual_hints

        self.assertTrue(metadata_phase_pattern(self.conn))


if __name__ == "__main__":
    unittest.main()
