from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db import connect
from app.fingerprint_cache import SqliteFingerprintCache
from stager_core.fingerprint import book_id_from_paths, file_fingerprint


class FingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, data: bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_order_independence(self) -> None:
        a = self._write("a.mp3", b"alpha-content")
        b = self._write("b.mp3", b"beta-content")
        id_ab = book_id_from_paths([a, b])
        id_ba = book_id_from_paths([b, a])
        self.assertEqual(id_ab, id_ba)

    def test_same_content_different_path_same_id(self) -> None:
        data = b"shared-audio-bytes"
        p1 = self._write("folder1/book.mp3", data)
        p2 = self._write("folder2/renamed.mp3", data)
        self.assertEqual(book_id_from_paths([p1]), book_id_from_paths([p2]))
        self.assertEqual(file_fingerprint(p1), file_fingerprint(p2))

    def test_split_files_different_ids(self) -> None:
        p1 = self._write("split/part01.mp3", b"part-one")
        p2 = self._write("split/part02.mp3", b"part-two")
        self.assertNotEqual(book_id_from_paths([p1]), book_id_from_paths([p2]))

    def test_small_file_edge_case(self) -> None:
        data = b"tiny"
        path = self._write("small.mp3", data)
        fp = file_fingerprint(path)
        self.assertEqual(len(fp), 64)
        self.assertEqual(fp, file_fingerprint(path))


class FingerprintCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = connect(self.root / "test.db")
        self.cache = SqliteFingerprintCache(self.conn)

    def tearDown(self) -> None:
        self.cache.flush()
        self.conn.close()
        self.tmp.cleanup()

    def _write(self, rel: str, data: bytes) -> Path:
        path = self.root / "books" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_cache_hit_skips_file_read(self) -> None:
        path = self._write("book.mp3", b"cached-audio-bytes")
        rel = "book.mp3"
        st = path.stat()
        expected = file_fingerprint(
            path, stat_result=st, cache=self.cache, rel_path=rel
        )
        self.cache.flush()

        with patch(
            "stager_core.fingerprint._read_fingerprint_bytes",
            side_effect=AssertionError("file read on cache hit"),
        ):
            cached = file_fingerprint(
                path, stat_result=st, cache=self.cache, rel_path=rel
            )
        self.assertEqual(cached, expected)

    def test_cache_invalidates_on_content_change(self) -> None:
        path = self._write("book.mp3", b"version-one-bytes")
        rel = "book.mp3"
        fp_v1 = file_fingerprint(path, cache=self.cache, rel_path=rel)
        self.cache.flush()

        path.write_bytes(b"version-two-is-longer")
        fp_v2 = file_fingerprint(path, cache=self.cache, rel_path=rel)
        self.assertNotEqual(fp_v1, fp_v2)

    def test_cache_persists_across_instances(self) -> None:
        path = self._write("persist.mp3", b"persist-bytes")
        rel = "persist.mp3"
        expected = file_fingerprint(path, cache=self.cache, rel_path=rel)
        self.cache.flush()
        self.conn.close()

        conn2 = connect(self.root / "test.db")
        cache2 = SqliteFingerprintCache(conn2)
        st = path.stat()
        cached = file_fingerprint(
            path, stat_result=st, cache=cache2, rel_path=rel
        )
        cache2.flush()
        conn2.close()
        self.assertEqual(cached, expected)

    def test_prune_missing_removes_stale_paths(self) -> None:
        path = self._write("gone.mp3", b"will-delete")
        rel = "gone.mp3"
        file_fingerprint(path, cache=self.cache, rel_path=rel)
        self.cache.flush()
        path.unlink()

        removed = self.cache.prune_missing(self.root / "books")
        self.assertEqual(removed, 1)
        self.assertIsNone(self.cache.get(rel, 10, 0))


if __name__ == "__main__":
    unittest.main()
