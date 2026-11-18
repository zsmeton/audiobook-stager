from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.api import ConflictApprove, ConflictSaveEditsBody, ConflictSeedEdit, approve_conflict, holder, save_conflict_edits
from app.db import _utcnow, connect
from app.scan import ScanManager
from app.session import StagingSession
from stager_core.staging import compute_target_key


def _insert_seed(
    conn,
    book_id: str,
    author: str,
    title: str,
    *,
    file_source: str,
    file_name: str,
    size_bytes: int,
) -> None:
    files = [{"name": file_name, "source": file_source, "size_bytes": size_bytes}]
    conn.execute(
        """
        INSERT INTO books (
            id, source_path, source_path_parts, top_level_pack, parent_context,
            grouping, flatten_name, flatten_target, files_json, status,
            suggested_author, suggested_title, chosen_author, chosen_title,
            confidence, staged_path, tags_json, candidates_json, lookup_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0.5, '', '{}', '[]', 'ok', ?)
        """,
        (
            book_id,
            "seed/book",
            '["seed","book"]',
            None,
            None,
            "flat",
            title,
            "",
            json.dumps(files),
            author,
            title,
            author,
            title,
            _utcnow(),
        ),
    )
    conn.commit()


class ConflictApproveApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.books_root = self.root / "src"
        self.library_root = self.root / "lib"
        self.books_root.mkdir()
        self.library_root.mkdir()

        self.old_key = compute_target_key("Author", "Title")
        author_dir, title_dir = self.old_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        target_dir.mkdir(parents=True)
        (target_dir / "existing.mp3").write_bytes(b"x" * 100)

        seed_path = self.books_root / "seed" / "book.m4b"
        seed_path.parent.mkdir(parents=True)
        seed_path.write_bytes(b"y" * 50)

        self.conn = connect(self.root / "test.db")
        _insert_seed(
            self.conn,
            "seed1",
            "Author",
            "Title",
            file_source="seed/book.m4b",
            file_name="book.m4b",
            size_bytes=50,
        )

        holder.conn = self.conn
        holder.session = StagingSession(self.books_root, self.library_root)
        holder.session.rebuild_target_indexes()
        holder.manager = ScanManager(
            self.conn, self.books_root, self.library_root, holder.session
        )
        self.new_key = compute_target_key("Author", "New Title")

    def tearDown(self) -> None:
        holder.session = None
        holder.conn = None
        holder.manager = None
        holder.session = None
        self.conn.close()
        self.tmp.cleanup()

    def test_approve_seed_with_metadata_override_stages_new_path(self) -> None:
        result = approve_conflict(
            self.old_key,
            ConflictApprove(
                winner_side="seed1",
                chosen_author="Author",
                chosen_title="New Title",
            ),
        )

        row = self.conn.execute(
            "SELECT status, staged_path, chosen_title FROM books WHERE id = 'seed1'"
        ).fetchone()
        self.assertEqual(row["status"], "staged")
        self.assertEqual(row["staged_path"], self.new_key)
        self.assertEqual(row["chosen_title"], "New Title")

        author_dir, title_dir = self.new_key.split("/", 1)
        staged_file = self.library_root / author_dir / title_dir / "book.m4b"
        self.assertTrue(staged_file.is_file())
        self.assertEqual(result["conflicts"], [])

    def test_save_conflict_edits_updates_all_pending_books(self) -> None:
        _insert_seed(
            self.conn,
            "seed2",
            "Author",
            "Title",
            file_source="seed/other.m4b",
            file_name="other.m4b",
            size_bytes=60,
        )
        (self.books_root / "seed" / "other.m4b").write_bytes(b"z" * 60)

        result = save_conflict_edits(
            self.old_key,
            ConflictSaveEditsBody(
                edits=[
                    ConflictSeedEdit(book_id="seed1", chosen_author="Author", chosen_title="Book One"),
                    ConflictSeedEdit(book_id="seed2", chosen_author="Author", chosen_title="Book Two"),
                ]
            ),
        )

        self.assertEqual(result["saved"], 2)
        self.assertEqual(result["errors"], [])
        row1 = self.conn.execute(
            "SELECT chosen_title FROM books WHERE id = 'seed1'"
        ).fetchone()
        row2 = self.conn.execute(
            "SELECT chosen_title FROM books WHERE id = 'seed2'"
        ).fetchone()
        self.assertEqual(row1["chosen_title"], "Book One")
        self.assertEqual(row2["chosen_title"], "Book Two")

    def test_approve_seed_over_library_replaces_and_stages(self) -> None:
        result = approve_conflict(
            self.old_key,
            ConflictApprove(winner_side="seed1"),
        )

        row = self.conn.execute(
            "SELECT status, staged_path FROM books WHERE id = 'seed1'"
        ).fetchone()
        self.assertEqual(row["status"], "staged")
        self.assertEqual(row["staged_path"], self.old_key)
        self.assertEqual(result["conflicts"], [])

        author_dir, title_dir = self.old_key.split("/", 1)
        target_dir = self.library_root / author_dir / title_dir
        self.assertFalse((target_dir / "existing.mp3").exists())
        staged_file = target_dir / "book.m4b"
        seed_path = self.books_root / "seed" / "book.m4b"
        self.assertTrue(staged_file.is_file())
        self.assertTrue(os.path.samefile(seed_path, staged_file))


if __name__ == "__main__":
    unittest.main()
