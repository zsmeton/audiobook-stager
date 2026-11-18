# Persistence and filesystem behavior

Map of how the Audiobook Stager process uses SQLite and the books/library trees. Describes what the code does today—not a target design.

Paths below use config roots from environment variables (`STAGING_CONFIG_ROOT` / `STAGER_CONFIG_ROOT`, `BOOKS_ROOT`, `AUDIOBOOKS_ROOT`); see `stager_core/paths.py` and `app/settings.py`.

---

## Observed behavior

### SQLite database location and connection

- Default DB file: `{config_root}/stager.db` (`app/settings.py:13-16`).
- Opening a DB: `app/db.py:connect` creates parent dirs, opens SQLite with `check_same_thread=False`, sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=10000` (`app/db.py:496-501`), runs `executescript(SCHEMA)` (`app/db.py:502`), then `_migrate_schema` (`app/db.py:503`), `ensure_auto_defaults` (`app/db.py:504`), `ensure_session_meta_defaults` (`app/db.py:505`), and `commit`.
- Production caller: `app/main.py:44` on startup (`connect(db_path())`). Tests and tools call `connect` directly with arbitrary paths.

### Tables and important columns

| Table | Role | Notable columns |
|-------|------|-----------------|
| `scans` | Scan run metadata | `status`, progress counters (`books_discovered`, `books_complete`, `library_files_indexed`, `scan_phase`, …) (`app/db.py:50-66`) |
| `books` | One row per discovered book (`books.id` = fingerprint id) | `source_path`, `files_json`, `status`, `staged_path`, suggested/chosen metadata + `*_set` pin flags, `merged_into`, `lvi_match_json` (`app/db.py:68-94`, migrations `app/db.py:336-441`) |
| `library_targets` | Persisted snapshot of library index (per target key) | `target_key`, `author_dir`, `title_dir`, `files_json`, `tags_json` (`app/db.py:210-217`) |
| `session_meta` | Single row `id='default'` | `last_scan_id`, `last_scan_finished_at`, `source_book_count`, `library_target_count` (`app/db.py:219-227`) |
| `file_fingerprints` | Fingerprint cache for discovery | PK `(rel_path, algo_version)`; lookup by `size_bytes`, `mtime_ns` (`app/db.py:285-296`, `app/fingerprint_cache.py:56-66`) |
| `schema_flags` | One-time migration markers | `key`, `applied_at` (`app/db.py:444-451`) |
| `conflict_resolutions` | Persisted conflict winners | `target_key`, `winner_side` (`app/db.py:109-113`) |
| `book_merges` | Merge group membership | `primary_book_id`, `member_book_id` (`app/db.py:115-119`) |
| `activity_lock` | Operator activity window | `locked_until`, `last_reason` (`app/db.py:203-208`, `app/activity_lock.py`) |
| `api_cache`, `auto_*`, `lookup_decisions`, `decision_outcomes`, `auto_change_feedback` | Metadata cache, automation, append-only logs | See `app/db.py:96-283` |

### Schema creation and migration

**Base schema:** `SCHEMA` string in `app/db.py:49-297` — `CREATE TABLE IF NOT EXISTS` for all tables plus indexes.

**Incremental `_migrate_schema(conn)`** (`app/db.py:300-441`): always runs on every `connect`. Uses `PRAGMA table_info(<table>)` to detect missing columns, then `ALTER TABLE … ADD COLUMN`. Observed steps:

- `auto_actions`: `review_outcome`, `min_confidence` (`app/db.py:301-305`)
- `scans`: `books_found` and progress columns; backfill `books_discovered` / `books_complete` from legacy columns (`app/db.py:306-335`)
- `books`: `merged_into`, series/chosen columns, pin `*_set` columns with one-time backfill when pin columns first added (`app/db.py:336-387`)
- `_repair_false_chosen_pins(conn)` after pin column work (`app/db.py:388`)
- Create `file_fingerprints` if table missing (`app/db.py:389-410`)
- `auto_settings`: `scan_manual_hints`, `lvi_search`, `lvi_boost`, title extraction JSON columns (`app/db.py:411-436`)
- `books`: `lvi_match_json` (`app/db.py:437-441`)

**`schema_flags` one-shot migrations** (`app/db.py:444-494`):

- Table ensured by `_ensure_schema_flags` (`app/db.py:444-452`).
- `repair_false_chosen_pins_v1`: if flag absent, clears `chosen_*_set` where chosen text equals suggested; then sets flag (`app/db.py:469-494`). Tests reset flags to re-run (`tests/test_chosen_pin_migrate.py:87-108`).

**Reachability when opening an old DB:** Any DB opened through `connect` receives full `SCHEMA` idempotent creates, full `_migrate_schema` column adds, pin backfill only when new pin columns were added in that session’s migration path, and `repair_false_chosen_pins_v1` at most once unless `schema_flags` row is removed. No down-migrations or version table beyond `schema_flags`.

### Fingerprint identity (files and books)

**Per-file fingerprint** (`stager_core/fingerprint.py:39-60`):

- `ALGO_VERSION = 1` (`stager_core/fingerprint.py:8`).
- Uses `st_size`, `st_mtime_ns`; hash = SHA-256 of `size|head|tail` where head/tail are 1 MiB chunks (whole file if `< 2 MiB`) (`stager_core/fingerprint.py:22-36`, `27-31`).
- Optional `FingerprintCache`: hit on `(rel_path, size_bytes, mtime_ns, algo_version)` (`app/fingerprint_cache.py:56-66`).

**Book id** (`stager_core/discovery.py:306-310`, `stager_core/fingerprint.py:63-67`):

- Collect per-file fingerprints for all files in the unit; `book_id = SHA1("|".join(sorted(fingerprints)))[:12]`.
- Order of files in the folder does not change id (`tests/test_fingerprint.py:27-32`).
- Same bytes at different paths → same file fingerprint and same single-file book id (`tests/test_fingerprint.py:34-39`).
- Different file sets → different ids (`tests/test_fingerprint.py:41-44`).

**Persistence:** `SqliteFingerprintCache` stores rows in `file_fingerprints`; `prune_missing(books_root)` deletes rows whose `rel_path` no longer exists under books root (`app/fingerprint_cache.py:112-144`). Scan uses `OverlayFingerprintCache` over SQLite (`app/scan.py:310-311`).

**Inference (labeled):** Two books are “the same work” in the DB only when they share the same fingerprint-derived `books.id`; content edits that change fingerprints yield a new id and orphan the old row after prune (`tests/test_scan_dedupe.py:269-300`).

### `library_index` and `inode_index` in `StagingSession`

**Definitions** (`app/session.py:42-49`):

- `library_index`: `dict[target_key, LibrarySide]` — file list + tags per library target (`stager_core/conflicts.py` / `LibrarySide`).
- `inode_index`: `dict[inode, list[relative library paths]]`.

**Population:**

- `rebuild_target_indexes` walks `library_root` via `build_target_indexes` (`app/session.py:59-72`, `stager_core/target_index.py:84-156`).
- `try_hydrate_from_db` loads `library_targets` from DB and rebuilds inode map by `stat` on each cached `relative_path` (`app/session.py:253-287`, `app/db.py:694-715`, `app/session.py:204-218`).

**Updates:**

- After scan: `persist_scan_snapshot` replaces all `library_targets` and updates `session_meta` (`app/session.py:220-238`, `app/db.py:623-654`).
- Per-target: `persist_library_target` upserts or deletes (`app/session.py:240-250`).
- After stage/unstage/replace: `apply_stage`, `apply_unstage`, `apply_replace_library` mutate in-memory indexes then optionally persist (`app/session.py:106-166`).
- After staging API calls: `merge_inode_index` merges path lists from the staging copy used during `os.link` (`app/session.py:100-104`, e.g. `app/api.py:1153-1155`).

**What each cache holds:**

- `library_index`: logical targets keyed by `Author/Title` or `Author/Series/Title-folder` (see layout); each side lists audio files with `relative_path`, `name`, `size_bytes` (`stager_core/target_index.py:131-140`).
- `inode_index`: all library paths known to share a given inode (hardlink siblings) (`stager_core/target_index.py:141-142`).

**Staging detection:** `analyze_book_staging` / `book_already_staged` mark a source file “linked” if its source inode appears in `inode_index` (`stager_core/staging.py:206-243`, `278-288`). Scan sets `books.status` to `staged` / `partial_staged` from this, not from `staged_path` alone (`app/scan.py:526-538`, `809-821`).

**Hardlink correctness dependency:** Staging uses `os.link` (`stager_core/staging.py:426-427`). Unstage only removes library names that `same_inode` with source (`stager_core/staging.py:735-740`). Session indexes must list paths after link so later scans detect “already staged”; stale inode cache can mis-report until `rebuild_target_indexes` or merge after stage (`app/session.py:141-164`).

**Target key from disk layout** (`stager_core/target_index.py:30-37`): library path with 3 parts → `author/title` (flat); ≥4 parts → first three components `author/series/title-folder`.

### Hardlink rules

- **Mechanism:** `os.link(src, dst)` for stage, partial complete, and merged stage (`stager_core/staging.py:426-427`, `536-537`, `907-908`).
- **Same mount:** Documented operator requirement (`README.md:28`); **not** enforced in application startup or health checks (`app/api.py:545-628`). E2E tests assert `st_dev` match when asserting hardlinks (`tests/e2e/helpers.py:74`).
- **Idempotent link:** If `dst` exists and `same_inode(src, dst)`, skip and refresh `inode_index` (`stager_core/staging.py:415-423`).
- **Name collision:** If `dst` exists with different inode → `OSError` message containing `name_collision` → classified status `name_collision` (`stager_core/staging.py:424-424`, `346-351`, `435-437`).
- **Link failure / partial failure:** On `OSError` during full stage, if target dir was created in this call, `shutil.rmtree(target_dir)`; else if dir empty, `rmdir` (`stager_core/staging.py:438-441`). Merged stage uses same pattern (`stager_core/staging.py:916-922`).
- **`stage_book_author_title` blocks partial:** If inode analysis says `partial_staged`, returns without linking (`stager_core/staging.py:390-394`).
- **Unstage (destage):** For each book file, require source file present, library file present, `same_inode`; then `dst.unlink()` only (`stager_core/staging.py:725-741`). Foreign file at expected name → `inode_mismatch`, no unlink (`stager_core/staging.py:735-738`, `tests/test_auto_revert.py:64-72`). Prune empty dirs from target up toward `library_root` (`stager_core/staging.py:743-749`).
- **Destaged rescan:** If DB says `staged` but inode analysis says not staged and not partial, scan clears to `pending` and empty `staged_path` before upsert (`app/scan.py:559-572`, `tests/test_destage_rescan.py:56-73`).

### Library layout (path builder)

**Target key / directory** (`stager_core/staging.py:300-332`):

- Sanitized `author_dir` = `sanitize_folder_name(author or "Unknown Author")`.
- **No series** (empty/whitespace `series`): `library_root/author_dir/title_name` where `title_name = sanitize_folder_name(title)`; target key `author_dir/title_name` (`stager_core/staging.py:323-326`, `307-309`).
- **With series:** `library_root/author_dir/series_dir/title_name`; `title_name = format_title_folder(title, series_index)` → optional `"<index> - <title>"` (`stager_core/staging.py:328-332`, `291-297`); key `author_dir/series_dir/title_name` (`stager_core/staging.py:310-312`).
- **Series pinned empty:** `effective_series_state == "confirmed_none"` → `target_key_preview` calls `compute_target_key(author, title)` only (`stager_core/metadata/effective.py:152-153`, `tests/test_series_patch.py:97-111`).

### Partial stage, replace, unstage, directory pruning

| Operation | Disk | Database / session |
|-----------|------|---------------------|
| **Partial stage (detected)** | Some `os.link`s may already exist under target dir | Scan sets `status='partial_staged'`, `staged_path` from linked paths (`app/scan.py:536-538`) |
| **Complete partial** (`complete_partial_stage`) | Links only `unlinked` files; collision rules same as full stage; on error may `rmdir` if created empty dir (`stager_core/staging.py:452-573`) | API updates `books` status/path; `merge_inode_index` + `apply_stage` on success (`app/api.py:1947-1985`) |
| **Remove extras** | `unlink` audio extras in target dir (inodes not in source set); `_prune_empty_dirs_up_to` (`stager_core/staging.py:576-636`, `639-646`) | May promote to `staged`; updates `library_targets` via `apply_stage` (`app/api.py:2000-2063`) |
| **Replace library target** | Unlinks all audio under resolved 2-level target; prunes empty dirs; leaves non-audio (`stager_core/staging.py:657-697`, `tests/test_library_replace.py:21-33`) | `apply_replace_library` drops target from indexes; `delete_library_target` or upsert (`app/session.py:126-139`, conflict approve `app/api.py:1091-1094`) |
| **Unstage / revert** | Inode-checked unlinks + empty-dir prune (`stager_core/staging.py:700-762`) | `books`: `pending`, clear `staged_path` (`app/api.py:2650-2657`); `apply_unstage` + `persist_library_target` (`app/session.py:106-124`) |
| **Full stage success** | `os.link` all files; update `inode_index` in memory | `books.staged`, `staged_path`; session `apply_stage` (`app/api.py:1108-1155`) |

**Partial promotion without API:** After scan, `_reconcile_partial_after_scan` may promote row if analysis becomes `already_staged` (`app/scan.py:893-901`, `app/api.py:436-460`).

### Scan ↔ DB coupling (staging status)

- Upsert computes `status` / `staged_path` from `book_already_staged` + destaged guard (`app/scan.py:526-573`, `681-779`).
- `ON CONFLICT(id)`: preserves existing `status` if already `'skipped'` or `'staged'` (does **not** preserve `'partial_staged'`) (`app/scan.py:705-708`).
- Orphan rows not in latest discovery set: metadata migrate then `delete_books_by_ids` (`app/scan.py:869-883`, `app/db.py:943-1019`).

---

## Invariants (enforced in code)

Each item is a behavior the implementation relies on, with citation.

1. **Book primary key = content fingerprint id** — discovery assigns `FlatBook.id` from sorted file fingerprints (`stager_core/discovery.py:306-310`).

2. **Staged vs not (scan)** — `books.status` for staging derives from inode membership in `inode_index`, not `staged_path` alone (`app/scan.py:526-538`); destaged clears stale `staged` when links gone (`app/scan.py:559-572`).

3. **Unstage only same inode** — `unstage_book` unlinks `dst` only when `same_inode(src, dst)` (`stager_core/staging.py:735-740`).

4. **No overwrite by name** — existing library file at destination with different inode aborts with `name_collision` (`stager_core/staging.py:424-424`, `534-534`).

5. **Full stage refuses partial** — `stage_book_author_title` exits early on `partial_staged` (`stager_core/staging.py:390-394`).

6. **Fingerprint cache validity** — SQLite cache returns fingerprint only when `rel_path`, `size_bytes`, `mtime_ns`, and `algo_version` match (`app/fingerprint_cache.py:56-66`).

7. **Pin flags protect chosen fields on rescan** — upsert keeps `chosen_*` when `chosen_*_set = 1` (`app/scan.py:715-729`).

8. **Library target persistence** — `library_targets` rows mirror `library_index` after scan snapshot (`app/db.py:623-654`, `app/session.py:228-230`).

9. **Hydration gate** — `try_hydrate_from_db` requires fresh `last_scan_finished_at` (≤24h), `count_books > 0`, non-empty `library_targets` (`app/session.py:259-277`).

10. **Conflict library side** — library appears in conflict when target has files but not all source inodes are linked (`stager_core/conflicts.py:218-243`).

11. **Merge groups exclude library conflicts** — merge detection skips groups with `has_library_conflict` (`stager_core/merges.py:41-52`).

---

## Inference (labeled)

- **Same mount for hardlinks:** Required for `os.link` to succeed; documented externally (`README.md:28`) but not validated at runtime in `app/` (unknown enforcement path—would need deployment/docs review).
- **`books.status = 'staged'` with live links:** Upsert can keep `staged` even if `ON CONFLICT` blocks status refresh (`app/scan.py:705-708`); destaged path compensates when links disappear (`app/scan.py:559-572`).
- **`library_targets` can drift** until next `rebuild_target_indexes` / `persist_scan_snapshot` / per-target persist after mutations.
- **`replace_library_target` / `apply_replace_library`** use 2-level `compute_target_key(author, title)` without series (`app/session.py:127`, `stager_core/staging.py:657-659`); series layouts may need different paths (verify at `app/api.py:1089-1094` call sites).

---

## Tests that lock this

| Area | Test module |
|------|-------------|
| Fingerprints & cache | `tests/test_fingerprint.py` |
| Fingerprint id + prune | `tests/test_scan_dedupe.py` (`FingerprintRescanPruneTests`) |
| Partial staging / extras | `tests/test_partial_staging.py` |
| Unstage / inode guard | `tests/test_auto_revert.py` |
| Destaged → pending | `tests/test_destage_rescan.py` |
| Series layout & pinned empty series | `tests/test_series_staging.py`, `tests/test_series_patch.py` |
| Library replace | `tests/test_library_replace.py` |
| Target index / inode parity | `tests/test_target_index.py` |
| Session DB snapshot hydrate | `tests/test_session_persistence.py` |
| Pin migration / `schema_flags` | `tests/test_chosen_pin_migrate.py` |
| Conflicts / merges grouping | `tests/test_conflicts.py`, `tests/test_merge_groups.py` |
| Staging session indexes | `tests/test_staging_session.py` |
| Library cache | `tests/test_library_cache.py` |

---

## Single-operator assumptions

- **`activity_lock`:** Operator API actions call `renew_activity_lock`, extending `locked_until` by `auto_settings.lock_timeout_minutes` (`app/activity_lock.py:13-27`). Scheduled auto-run skips when lock active unless bypassed (`app/auto.py:94-95`, `121`).
- **One SQLite DB per deployment** with process-wide `DB_LOCK` (`app/db.py:24`, `app/db.py:953+`). WAL allows concurrent readers; writers serialize on `DB_LOCK`.
- **One logical operator** implied by unstaged cooperative lock—not cluster-safe for multi-writer staging without external coordination (not implemented).

---

## Unknowns

| Topic | Notes |
|-------|--------|
| Runtime same-mount check | No check in `app/api.py` health; only README and e2e helpers (`tests/e2e/helpers.py:74`). |
| `link_error` beyond collision/missing | Classified generically (`stager_core/staging.py:346-351`); no dedicated test for cross-device link failure in unit tests. |
| Windows vs POSIX inode semantics | Code uses `st_ino`; behavior on platforms without stable inode semantics—would need `stager_core/staging.py` + platform testing. |
| `replace_library_target` with series metadata | API passes author/title only (`app/api.py:1091`); full 3-level replace behavior **unknown**—cite conflict approve path. |
| Exact `STAGING_CONFIG_ROOT` on user machine | Redacted; resolved via `stager_core/paths.py:21-25`. |