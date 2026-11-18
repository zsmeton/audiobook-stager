# Scale and cost (observed)

Evidence for database and API rework decisions. Describes cost only; no engine or framework recommendations.

---

## Per-path cost

### 1. `GET /api/books` (`list_books`)

| Aspect | Classification | Evidence |
|--------|----------------|----------|
| DB read | **O(library)** where library = row count in `books` | `SELECT * FROM books ORDER BY source_path` loads every column for every row (`app/api.py:229-233`, `app/session.py:170`, `184`). |
| Conflict / merge refresh | **O(library)** per list call, **two extra full-table reads** | `_compute_conflicts()` always calls `refresh_resolution_groups`, which runs `SELECT * FROM books` in both `refresh_conflicts` and `refresh_merges` (`app/api.py:279-286`, `app/session.py:168-196`). |
| Python work (list handler) | **O(library)** | `_all_book_rows()` then `_filter_books()` iterates all rows; partitioned mode runs `_filter_books` twice (staging + partial) (`app/api.py:810-866`, `894-908`). |
| Pagination slice | **O(page)** on filtered lists only when `partitioned=false` | Default `limit=500`, `offset=0` (`app/api.py:876-877`, `916`). |
| Partitioned slice | **Staging only bounded**; partial unbounded | `staging[offset : offset + limit]`; `partial` and `conflicts` / `merges` returned whole (`app/api.py:894-908`). |
| Stats query | **O(library)** (group-by over table) | `SELECT status, COUNT(*) AS c FROM books GROUP BY status` (`app/api.py:887-889`). |

**Observed SQL (books list path)**

- List handler: `SELECT * FROM books ORDER BY source_path` (`app/api.py:233`).
- Not observed: server-side `WHERE` for `status`, `q`, or `section`; those filters run in `_filter_books` in Python (`app/api.py:810-866`).
- Conflict path (on every `_compute_conflicts()`): `SELECT * FROM books ORDER BY source_path` ×2 plus `SELECT target_key, winner_side FROM conflict_resolutions` (`app/session.py:170-171`, `app/db.py:571`).

**Payload bounding (partitioned mode, UI default)**

| Payload field | Bounded? | Notes |
|---------------|----------|-------|
| `staging` | **Yes (default 500)** | Only when `partitioned=true`; slice uses `limit`/`offset` (`app/api.py:907`). |
| `partial` | **No** | All `partial_staged` rows passing filters (`app/api.py:899-902`). |
| `conflicts` | **No** | Full `conflict_groups` list (`app/api.py:904`). |
| `merges` | **No** | Full `merge_groups` from session cache (`app/api.py:905`, `884`). |
| Per-book `files` | Included | `row_to_book` always parses `files_json` (`app/db.py:519-536`); list uses `include_files=False` only for staging analysis attachment, not to strip `files` (`app/api.py:864`). |
| `candidates` | Included | Decoded in `row_to_book` (`app/db.py:560`); LVI refresh on each listed book (`app/api.py:261`, `864-865`). |

**Conflict group computation cost**

- `detect_conflict_groups`: **O(library)** scan of eligible rows, grouped by target key; per-group work can touch seed `files` and `inode_index` (**O(files per book)** in worst case) (`stager_core/conflicts.py:311-399`).
- Conflict sides embed full `files` and `candidates` from each row (`stager_core/conflicts.py:250-275`).

**Merge list path**

- Same refresh entry point as conflicts: `refresh_resolution_groups` loads the full `books` table again in `refresh_merges` (`app/session.py:182-192`).
- `list_books` calls `_compute_conflicts()` (full refresh) then `get_merges()` without a second refresh (`app/api.py:883-884`, `289-296`) — **observed: two `SELECT * FROM books` inside one `_compute_conflicts`, not four**.
- Total **three** full `books` table reads per `list_books`: `_all_book_rows` + `refresh_conflicts` + `refresh_merges` (`app/api.py:882`, `app/session.py:168-192`).

**Inference:** At 50k rows, each `list_books` touches ~150k row-equivalents of SQLite I/O and JSON parsing if conflict refresh runs every time (3× full table).

### 2. Conflict refresh (session)

| Aspect | Cost |
|--------|------|
| DB | **O(library)** — `SELECT * FROM books ORDER BY source_path` + full `conflict_resolutions` (`app/session.py:168-171`). |
| CPU / memory | **O(library)** — `row_to_book` for every row; `detect_conflict_groups` over in-memory dicts (`app/session.py:172-180`). |
| Uses indexes | `library_index`, `inode_index` in memory (not SQL) (`app/session.py:178-179`). |

**Observed:** Runs on every `_compute_conflicts()` call, including every `list_books` (`app/api.py:279-286`, `883`).

### 3. Merge list path

| Aspect | Cost |
|--------|------|
| DB | **O(library)** — second `SELECT * FROM books` in same refresh batch (`app/session.py:182-185`). |
| CPU | **O(library)** — `detect_merge_groups` (`stager_core/merges.py:13-70`). |

**Observed:** Merge groups omit library-side conflicts (`stager_core/merges.py:51-52`); still linear in pending-eligible books.

### 4. `library_index` and `inode_index`

| Aspect | Cost / size |
|--------|-------------|
| Build source | All audio files under `library_root` (`stager_core/target_index.py:98-156`). |
| Walk | **O(all files under library tree)** — `rglob("*")` then filter by `AUDIO_EXT` (`stager_core/target_index.py:100-105`). |
| Per audio file | `stat`, optional parallel `_index_one_file`; inode recorded (`stager_core/target_index.py:40-60`, `131-142`). |
| Tag reads | **O(library targets)** — up to 5 tag reads per target key (`stager_core/target_index.py:63-81`, `147-153`). |
| Relative size | **O(library audio files)** — one `LibrarySide` per target key; `inode_index` keyed by inode (`stager_core/target_index.py:131-142`). |

**When rebuilt (observed)**

- Full scan: `session.rebuild_target_indexes` on indexing thread (`app/scan.py:331-337`, `app/session.py:59-76`).
- Hydration (&lt;24h): `load_library_targets` + `build_inode_index_from_library_index` (no filesystem walk) (`app/session.py:253-286`, `app/db.py:698`).
- Process-global cache: `get_library_indexes` walks library **twice** if session not ready — separate `build_library_index` and `build_inode_index`, each calling `build_target_indexes` (`stager_core/library_cache.py:39-43`, `stager_core/conflicts.py:207`, `stager_core/staging.py:133`).

**Observed:** Session keeps both structures resident after build (`app/session.py:46-49`).

### 5. Fingerprint cache

| Store | Contents | Growth |
|-------|----------|--------|
| SQLite `file_fingerprints` | `rel_path`, `size_bytes`, `mtime_ns`, `algo_version`, `fingerprint` (PK `rel_path, algo_version`) (`app/db.py:285-293`) | **O(seed audio files)** — one row per relative path per algo version. |
| `OverlayFingerprintCache` | In-memory overlay keyed by `(rel_path, size_bytes, mtime_ns)` (`app/fingerprint_cache.py:16-44`) | Grows with distinct files touched in the active scan. |
| Compute | Head/tail 1 MiB hash (or full file if &lt;2 MiB) (`stager_core/fingerprint.py:10-36`) | **O(files)** during discovery; parallel workers default `min(32, cpu_count)` (`stager_core/discovery.py:157-161`, `268-274`). |

**Observed:** `prune_missing` scans all fingerprint rows (`app/fingerprint_cache.py:114-120`) — **O(cached paths)**.

### 6. Metadata lookup

| Mechanism | Observed behavior | Cost |
|-----------|-------------------|------|
| Concurrency | **Sequential per process** — `MetadataLookupService.resolve_book` holds `self._lock` (`stager_core/metadata/lookup.py:148-149`). |
| Scan metadata phase | **O(books)** sequential loop; one `resolve_book` per non-skipped book (`app/scan.py:390-422`). |
| MAM cookie | Separate `threading.Lock` on providers (`stager_core/metadata/providers.py:239-245`). |
| API cache DB | `ApiCache` uses its own lock (`stager_core/metadata/cache.py:16-19`). |

**Rate limiter defaults (`RateLimitedClient`)** — values to preserve if concurrency must not rise (`stager_core/metadata/ratelimit.py:46-67`, env overrides `stager_core/metadata/lookup.py:84-87`):

| Provider | Interval / cap |
|----------|----------------|
| `audnexus` | min 500 ms between calls (default; `AUDNEXUS_MIN_INTERVAL_MS`) |
| `openlibrary` | min 1000 ms (`OPENLIBRARY_MIN_INTERVAL_MS` default 1000 in ctor) |
| `google_books` | min 1000 ms (ctor default; not env-overridden in `lookup.py`) |
| `audible` | min 1000 ms (ctor default) |
| `mam` | leaky bucket **120 requests / 60 s** (`MAM_REQUESTS_PER_MINUTE` default 120) |

**Observed:** 429 handling adds cooldowns (e.g. Google daily disable path) (`stager_core/metadata/ratelimit.py:132-144`). HTTP timeout 45 s (`stager_core/metadata/ratelimit.py:192`).

**Inference:** Scan metadata duration at 50k new pending books is dominated by sequential lookups and provider intervals, not SQLite.

### 7. Scan

| Phase | Dominant cost | Long-running? |
|-------|---------------|---------------|
| Discovery | **O(files)** walk `rglob`, fingerprint all audio files, build `FlatBook` list (`stager_core/discovery.py:164-182`, `233-329`) | Yes |
| Library indexing (parallel) | **O(library files)** `build_target_indexes` (`app/scan.py:331-346`, `stager_core/target_index.py:84-156`) | Yes |
| LVI rebuild | **O(staged books)** — `SELECT * FROM books WHERE status = 'staged'` (`stager_core/metadata/lvi.py:108`, `app/scan.py:338-339`) | Scales with staged count |
| Metadata | **O(books)** sequential; skip lookup for already staged/skipped (`app/scan.py:575-579`, `390-422`) | Yes (often hours) |
| Per-book staging check | **O(files per book)** `book_already_staged` vs `inode_index` (`app/scan.py:526-528`) | Per book |

**UI polling (observed)**

- `SCAN_POLL_MS = 1500` (`static/app.js:32`).
- While scan `running`: `GET /api/scan/{scan_id}` then **`loadBooks()`** every poll (`static/app.js:4898-4908`).
- **Inference:** Active scan multiplies `list_books` cost (~every 1.5 s) on top of scan itself.

---

## What the UI requests

| Action | Request | Limit / partition |
|--------|---------|-------------------|
| Main book lists | `GET /api/books?partitioned=true&status=…` (+ optional `q`) (`static/app.js:4788-4795`) | **Does not send `limit` or `offset`** — server defaults `limit=500` apply only to `staging` slice (`app/api.py:876-877`, `907`). |
| Scan progress | `GET /api/scan/{id}` every 1.5 s + full `loadBooks` (`static/app.js:4901-4908`) | N/A |
| Single book detail | `GET /api/books/{id}` (various handlers) | Per-id |
| Title extraction preview | `limit: 10` in POST body only (`static/app.js:4653`) | Bounded (settings preview, not main list) |

**Observed rendering:** Client uses full `partial` array and all `conflicts` / `merges` (`static/app.js:4178-4186`, `3119-3127`). Staging list length is whatever the API returned (≤500 pending non-conflict non-merge by default server slice, but client-side filters also remove merge members — `static/app.js:4183-4185`).

---

## Rate limits and locks that exist today

| Lock | Scope |
|------|--------|
| `DB_LOCK` (`threading.RLock`) | SQLite access across app (`app/db.py:24`) |
| `_compute_conflicts_lock` | Serializes conflict/merge refresh (`app/api.py:91`, `282`) |
| `MetadataLookupService._lock` | One metadata resolve at a time (`stager_core/metadata/lookup.py:116-149`) |
| `RateLimitedClient` | Per-provider spacing and MAM bucket (`stager_core/metadata/ratelimit.py:46-88`) |
| `ApiCache._lock` | API response cache (`stager_core/metadata/cache.py:16`) |
| `OverlayFingerprintCache._lock` | Fingerprint overlay (`app/fingerprint_cache.py:21`) |
| `MetadataProviders._mam_lock` | MAM cookie rotation (`stager_core/metadata/providers.py:239`) |
| Scan thread | Single active scan thread per manager (`app/scan.py:279-304`) |
| Activity lock | DB-backed operator activity (`app/db.py:203-207`, `app/activity_lock.py`) |

---

## Memory at ~50 000 books / ~500 000 audio files

All figures below marked **(inference)** unless cited.

| Resident (process) | Basis |
|--------------------|--------|
| `session.library_index` + `session.inode_index` | **O(library audio files)** structures after index build (`app/session.py:46-49`). **(inference)** ~500k file entries if library holds most files. |
| `session.lvi` / `lvi_rows` | **O(staged books)** only (`stager_core/metadata/lvi.py:108`, `app/session.py:78-80`). **(inference)** ≪50k if minority staged. |
| `conflict_groups` / `merge_groups` | **O(conflict/merge groups × sides)**; sides include `files` + `candidates` (`stager_core/conflicts.py:250-275`). **(inference)** unbounded with collision rate. |
| SQLite page cache | **(inference)** proportional to DB size (50k book rows + JSON blobs + 500k fingerprint rows). |
| Transient per `list_books` | Three full row lists + filtered dicts + serialized JSON response. **(inference)** hundreds of MB if `candidates_json` large per row. |

**Sent to browser (partitioned `loadBooks`, default params)**

| Part | **(inference)** |
|------|-----------------|
| `staging` | ≤500 book objects (each with `files`, `candidates`, tags, LVI fields) (`app/api.py:907`, `app/db.py:519-560`). |
| `partial` | Up to all partial_staged books (unbounded). |
| `conflicts` / `merges` | All groups with nested sides/members. |
| `stats` | Small fixed map (`app/api.py:890-892`). |

**Observed:** Scan poll triggers this payload repeatedly during long scans (`static/app.js:4906-4908`).

---

## Indexes observed

**Created in schema (`app/db.py:106-107`, `121`, `164-201`, `256-263`, `280-283`, `295-296`)**

- `books`: `idx_books_status`, `idx_books_scan` (no index on `source_path`).
- `book_merges`: `idx_book_merges_primary`.
- `auto_actions`, `auto_change_feedback`, `lookup_decisions`, `decision_outcomes`: various.
- `file_fingerprints`: `idx_file_fp_lookup` on `(rel_path, size_bytes, mtime_ns, algo_version)`.

**Full-table scans observed (hot paths)**

| Query | Index use |
|-------|-----------|
| `SELECT * FROM books ORDER BY source_path` | **Full table scan** (no `source_path` index). |
| `SELECT * FROM books` (conflict refresh ×2) | **Full table scan**. |
| `SELECT status, COUNT(*) … GROUP BY status` | May use `idx_books_status` partially; still reads all matching rows. |
| `SELECT * FROM books WHERE status = 'staged'` (LVI) | Likely uses `idx_books_status`. |
| `file_fingerprints` point lookup | Uses `idx_file_fp_lookup` / PK (`app/fingerprint_cache.py:58-65`). |
| `SELECT * FROM library_targets` (hydrate) | PK table scan **O(target keys)** (`app/db.py:698`). |
| `prune_missing` fingerprint SELECT by `algo_version` | **Full scan** of `file_fingerprints` (`app/fingerprint_cache.py:114-119`). |

---

## Tests that lock bounded behavior

| Test module | What it asserts | Scale bounds? |
|-------------|-----------------|---------------|
| `tests/test_library_cache.py` | Cache identity and invalidation | No row/count limits |
| `tests/test_target_index.py` | Parity of unified vs legacy index builders | No |
| `tests/test_conflicts.py` | Conflict detection correctness | Small fixtures only |
| `tests/e2e/helpers.py` | `list_books` / `partitioned=true` helpers | No limit assertions |
| `tests/e2e/test_h_lvi.py` | Staging list after scan | No pagination tests |

**Observed:** No unit test fixes `list_books` `limit=500` or caps `conflicts`/`partial` payload size.

---

## Single-operator assumptions

- One human operator; no auth on API (`docs/rework/01-product-contract.md` cites `app/main.py`).
- One scan worker thread; second scan returns 409 (`app/scan.py:279-282`, `app/api.py:802-806`).
- One machine holds books root, library root, and SQLite DB.
- Metadata lookups serialized globally (`stager_core/metadata/lookup.py:148-149`).
- Session indexes treated as authoritative after scan; hydration within 24 h avoids re-walk (`app/session.py:35-36`, `271-272`).
- Hardlinks imply seeds and library on same volume (product contract).

---

## Unknowns

| Question | Would need |
|----------|------------|
| Typical `candidates_json` / `files_json` size at production scale | Sample `stager.db` or telemetry |
| Conflict/merge group counts at 50k pending | Workload distribution |
| Ratio of 500k files between seed vs library trees | Deployment layout |
| Whether `ORDER BY source_path` is acceptable with index added | Migration experiments (out of scope here) |
| Peak RSS during scan + poll | Runtime profiling |

---

## Summary table (cost class)

| Path | Cost class | UI trigger |
|------|------------|------------|
| `GET /api/books` (default UI) | **O(library)** DB ×3 + **O(library)** Python; staging slice **O(page)** | `partitioned=true`, no `limit` |
| Conflict refresh | **O(library)** | Every `list_books` via `_compute_conflicts` |
| Merge refresh | **O(library)** | Same refresh batch |
| `library_index` / `inode_index` build | **O(library files)** | Scan + optional double walk in `library_cache` |
| Fingerprint cache | **O(files)** storage and discovery | Scan discovery |
| Metadata lookup | **O(books)** sequential; providers rate-limited | Scan + manual lookup endpoints |
| Scan end-to-end | **O(files)** + **O(books)** × lookup latency | Long-running; UI polls 1.5 s |