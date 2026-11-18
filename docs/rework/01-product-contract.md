# Audiobook Stager — product contract (observed)

Descriptive map of what the running app does for a single operator today. No target architecture.

---

## Observed behavior

### Operator-facing surfaces

- **Web UI** (`static/index.html`, `static/app.js`, `static/style.css`): single page with sections **While you were away**, **Conflicts**, **Partial staging**, **Staging** (pending queue), toolbar **Start Scan** and **Auto-stage settings**, book detail dialog, conflict/merge resolve dialogs.
- **HTTP API** (`app/api.py`, prefix `/api`): all operator actions; no authentication middleware (`app/main.py`).
- **Persistence**: SQLite at `STAGER_CONFIG_ROOT/stager.db` (`app/settings.py:13-16`); library and seed trees on configured `BOOKS_ROOT` / `AUDIOBOOKS_ROOT` (`README.md:20-22`, `app/settings.py:19-24`).

### Library folder layout (system terms)

- **Target key** drives library relative paths via `compute_target_key` (`stager_core/staging.py:300-312`):
  - With **no series** (empty effective series): `Author/Title`.
  - With **series**: `Author/Series/{series_index} - {Title}` (`format_title_folder`, `stager_core/staging.py:291-297`, `resolve_staging_target` `315-332`).
- **Staging write**: `stage_book_author_title` creates library directories and **hardlinks** seed files with `os.link` (`stager_core/staging.py:402-432`). Hardlinks require seeds and library on the same mount (`README.md:28`).
- **Unstage / revert / “Unstage” in UI**: `unstage_book` removes library hardlinks that share inode with seeds (`stager_core/staging.py:700+`); UI label “Unstage” and bulk “Unstage Selected” (`static/app.js:52-55`, `2679-2693` `app/api.py`).

#### README vs UI vs code (layout wording)

| Source | States |
|--------|--------|
| `README.md:3` | Hardlink library described as **`Author/Title`** only. |
| `static/index.html:13` | Subtitle: hardlink to **`Author/Series/Title/`** layout. |
| `stager_core/staging.py:307-312` | **Both**: flat `Author/Title` when series empty; series path when series present. |
| `docs/pinning-model.md:18` | Pinned empty series ⇒ flat **`Author/Title/`** (`confirmed_none`). |

### Metadata model (operator view)

Per field (`author`, `title`, `series`, `series_index`) — `docs/pinning-model.md:8-16`, implemented in `stager_core/metadata/effective.py`:

- **Suggested**: last lookup winner; relookup may overwrite.
- **Chosen + `chosen_*_set`**: operator pin when `_set = 1`; UI **Manual** vs **Suggested** badges follow `_set`, not non-empty `chosen_*` (`docs/pinning-model.md:16-17`).
- **Effective**: pinned chosen else suggested (`effective_author` et al., `stager_core/metadata/effective.py:73-98`).
- **Empty pinned series**: `chosen_series_state` → `confirmed_none` forces flat layout (`stager_core/metadata/effective.py:101-107`).

**Save in detail form**: `PATCH /api/books/{id}` sets `_set = 1` for any `chosen_*` field present (`app/api.py:1711-1724`, `1726-1748`).

**Revert fields**: `revert_fields` / `revert_all` clears `_set` (`app/api.py:1699-1710`).

### Session and “do I need a scan?”

`GET /api/session/status` (`app/api.py:667-737`):

- **States**: `no_scan`, `stale_scan`, `fresh`, `scan_running`, `auto_running`.
- **`needs_scan`**: true when `no_scan` or `stale_scan`.
- **Stale**: last completed scan finished more than **`STALE_SCAN_HOURS` (24)** ago, or in-memory session not hydrated (`app/session.py:35`, `app/api.py:708-719`).

### Workflow: scan a seed folder

**Trigger**: `POST /api/scan` (`app/api.py:785-807`); blocked if auto-run is active (`789-798`); UI polls scan progress (`static/app.js:32`, `SCAN_POLL_MS`).

**What the operator sees**: bootstrap/scrim during first scan; progress phases **discovering → indexing → metadata** (`app/scan.py:61-63`, `ScanProgress`); stats and partitioned book lists after completion (`app/api.py:894-906`).

**What the system writes**:

1. **Filesystem**: read-only on seeds except hardlinks on approve; scan indexes existing library (`build_target_indexes` via session, `app/session.py:59-76`).
2. **SQLite**: row per discovered book in `books` (paths, files JSON, status, suggested/chosen metadata, confidence, candidates, tags); scan row in `scans` with counters; `lookup_decisions` during metadata; optional `api_cache` (`app/scan.py:513+` upsert path).
3. **In-memory session**: after scan completes, `library_index`, `inode_index`, LVI, conflict/merge groups refreshed; `session_meta` snapshot (`app/scan.py:457-469`, `app/session.py:220-238`).

**Scan phases (observed)**:

- Discover flat books under `books_root` (`stager_core/discovery.py`, invoked `app/scan.py:discover_books` path).
- Index library inodes for “already staged” detection (`book_already_staged`, `stager_core/staging.py:283-288`).
- Metadata lookup for books not skipped as already staged/skipped (`app/scan.py:540-579`).
- Prune orphan DB rows, reconcile partial staged (`app/scan.py:433-438`, `893+`).

**Manual hints on scan**: when auto setting `scan_manual_hints` is on, pinned author/title feed `ManualHints` (`app/scan.py:48-57`, `docs/pinning-model.md:37-39`).

**Destage on rescan** (operator term; code comment “destaged”): if DB says `staged` but library hardlinks are gone, scan resets book to **`pending`** and clears `staged_path` (`app/scan.py:555-573`). Test: `tests/test_destage_rescan.py`.

### Workflow: metadata lookup

**Trigger**: `POST /api/books/{book_id}/lookup` (`app/api.py:1781-1788`); optional body hints (`LookupHints`).

**Behavior**: `ScanManager.lookup_book_by_id` runs provider pipeline (`stager_core/metadata/lookup.py`, wired in `app/scan.py`). Pinned fields passed as lookup hints per pinning doc (`docs/pinning-model.md:36-37`).

**Writes**: updates `suggested_*`, `candidates_json`, `confidence`, `lookup_status`, logs `lookup_decisions` (see `app/db.py` insert helpers). Does not approve or hardlink.

**Settings → clear cache**: `POST /api/auto/cache/clear` deletes `api_cache` and sets `cache_relookup_pending` (`app/api.py:2455-2464`).

### Workflow: review

**Lists**: `GET /api/books?partitioned=1` returns `staging`, `partial`, `conflicts` slices (`app/api.py:894-906`). Pending books in conflict are excluded from staging section (`828-830`).

**Detail**: `GET /api/books/{id}` includes effective metadata, `target_key_preview`, staging analysis when relevant, LVI form match, tags, candidates (`app/api.py:1635+`, `row_to_book` in `app/db.py`).

**Operator edits**: `PATCH` book metadata; `POST` target-key-preview; duration endpoints for conflict/book (`app/api.py:1626`, `926`).

### Workflow: approve (stage)

**Trigger**: `POST /api/books/{book_id}/approve` or bulk `POST /api/books/bulk-approve` (`1889-1929`, `2068+`).

**Preconditions**: not already solely returning staged book; **blocked if `in_conflict`** (`1893-1894`).

**Reads for staging**: `_resolve_stage_metadata` → `resolve_winner_metadata` using effective pins and suggestions (`app/api.py:324-355`, `stager_core/conflicts.py:65+`).

**Filesystem**: hardlink into computed target dir (`stage_book_author_title`).

**Database on success** (`_commit_approve_book`, `1835-1886`):

- `status = staged`, `staged_path`, `chosen_*` columns updated to staged values.
- **`chosen_*_set` columns are not updated** (remain prior values — typically 0 after lookup-only flow).
- `decision_outcomes` row `action=approve`.
- `dismiss_auto_actions_for_book` (`1877`).
- Session `apply_stage`, `refresh_conflicts` (`1873-1877`, `1927-1928`).

**Operator sees**: book moves to staged filter; staged path shown (`static/app.js` staged list); detail shows metadata with Suggested badges if `_set` still 0 (`docs/pinning-model.md:22-24`).

### Workflow: skip / unskip

- **Skip**: `POST /api/books/{book_id}/skip` → `status=skipped` (`2145-2165`).
- **Unskip**: only from `skipped` → `pending` (`2168-2190`, bulk `2193+`).

Skipped books skip metadata on rescan (`app/scan.py:575-578`).

### Workflow: revert (unstage)

**Trigger**: `POST /api/books/{book_id}/revert` or bulk (`2679-2737`); UI “Unstage” calls same revert path (`static/app.js`).

**Allowed status**: `staged` or `partial_staged` (`2602-2604`).

**Filesystem**: `unstage_book` removes matching hardlinks.

**Database**: `status=pending`, `staged_path=''`, dismisses open `auto_actions` with feedback `rejected` (`2647-2665`, `2584-2599`).

**Does not** clear `chosen_*` or `_set` pins (only status/path).

### Workflow: partial stage

**Detection**: approve or scan finds some seed files already hardlinked at target → `partial_staged` (`stager_core/staging.py:390-394`, `app/scan.py:536-538`).

**Operator sees**: **Partial staging** section (`static/index.html` partial section, `app/api.py:834-836`).

**Actions**:

- **Complete linking**: `POST .../complete-partial` (`1932-1997`).
- **Remove extras**: `POST .../remove-extras` for stray library files (`2000+`).
- **Unstage**: same revert path as staged.

**Writes**: filesystem hardlinks for remaining files; DB status → `staged` or stays `partial_staged` with `error` if incomplete.

### Workflow: conflicts

**Detection**: `detect_conflict_groups` — multiple pending seeds targeting same `target_key` and/or library collision (`stager_core/conflicts.py`, session `refresh_conflicts` `app/session.py:168-180`).

**Operator sees**: Conflicts section, per-group dialog with sides (seeds vs **library** side id `LIBRARY_SIDE_ID`, `stager_core/conflicts.py:24`).

**Actions**:

- **Save edits** on seed metadata in conflict UI: `POST .../save-edits` sets **all four `chosen_*_set = 1`** (`app/api.py:991-998`).
- **Approve winner**: `POST .../approve` with `winner_side` (`1022-1161`):
  - Library winner → all conflict seeds marked `skipped` (`1046-1056`).
  - Seed winner → stage winner; other seeds `skipped` (`1130-1136`); may `replace_library_target` if library occupied same key (`1089-1094`).
- **Conflict merge**: `POST .../merge` delegates to `_perform_merge` (`1182-1211`).

**Persistence**: `conflict_resolutions` table via `save_conflict_resolution` (`1039-1040`).

**Approve blocked** for in-conflict books from main staging (`1893-1894`).

### Workflow: merges (non-conflict)

**Detection**: `detect_merge_groups` — 2+ pending seeds, same `target_key`, no library file collision (`stager_core/merges.py:13-57`).

**Actions**: preview `POST /merges/{key}/preview`, approve `POST /merges/{key}` (`1504-1550`), **unmerge** `DELETE /merges/{primary}` unstages primary and splits files (`1553-1612`).

**Writes**: combined `files_json` on primary, members `status=merged`, `book_merges` rows, single hardlink staging via `stage_merged_books` (`app/api.py:1409-1468`).

### Workflow: auto-stage

**Settings** (`GET/PATCH /api/auto/settings`): enabled, interval, `min_confidence`, `lock_timeout_minutes`, `scan_manual_hints`, LVI flags, title extraction mode (`app/api.py:2232-2305`).

**Run**: scheduled (`app/scheduler.py` + `try_scheduled_tick`, `app/auto.py:510-514`) or manual `POST /api/auto/run` (`2426-2443`). Auto-run **starts a full scan** then stages eligible pending books (`app/auto.py:292-327`, `356+`).

**Eligibility** (`stager_core/auto_eligibility.py:18-37`): `pending`, not in conflicts, **no field with `chosen_*_set`**, confidence ≥ min, has author and title.

**Filesystem**: same hardlink staging.

**Database**: book `staged`; inserts `auto_actions` for operator review (`428-449`); `decision_outcomes` `action=auto_stage` (`453-460`). Does not set `_set` flags on auto-stage (`412-416` SQL).

**While you were away**: `GET /api/auto/review` lists undismissed `auto_actions`; dismiss okay / revert records feedback (`2467-2544`, `2584-2599`).

**Activity lock**: operator actions call `_renew_lock` → extends `activity_lock.locked_until` by `lock_timeout_minutes` (`app/activity_lock.py:13-33`); scheduled auto defers when lock active (`app/auto.py:94-95`, `121-122`).

### Pinning: normal approve vs conflict/merge paths (contradiction)

Documented in `docs/pinning-model.md:22-25`:

- Normal **Approve** / auto-stage: copies effective values into `chosen_*` but leaves **`chosen_*_set = 0`** so UI stays Suggested and relookup can refresh suggestions.

**Observed code — normal approve** (`_commit_approve_book`):

```1851:1854:app/api.py
            UPDATE books SET
                status = ?, staged_path = ?, chosen_author = ?, chosen_title = ?,
                chosen_series = ?, chosen_series_index = ?,
```

(No `chosen_*_set` columns in this UPDATE.)

**Observed code — conflict save-edits** (always pins all fields edited in conflict UI):

```996:997:app/api.py
                    chosen_author_set = 1, chosen_title_set = 1,
                    chosen_series_set = 1, chosen_series_index_set = 1,
```

**Observed code — conflict approve** (pins only when request body includes any override):

```1074:1082:app/api.py
    if has_overrides:
        with DB_LOCK:
            holder.conn.execute(
                ...
                    chosen_author_set = 1, chosen_title_set = 1,
                    chosen_series_set = 1, chosen_series_index_set = 1,
```

**Observed code — merge approve** (`_perform_merge`): same pattern — sets all `_set = 1` **only when `has_overrides`** (`1426-1433` `app/api.py`).

**Contradiction (stated, not a prescribed fix)**: conflict **save-edits** always sets `_set = 1` for all four fields; normal **approve** never sets `_set` in SQL; conflict/merge **approve** sets `_set` only when explicit chosen overrides are sent — so post-resolution pinning behavior diverges from normal approve and from pinning doc’s “staging snapshot ≠ pin” rule (`docs/pinning-model.md:20-25`).

### Feature inventory

| Feature | What it does | Primary location | Tests (if any) |
|---------|----------------|------------------|----------------|
| Health | `/api/health` aggregates DB, scan, library paths, activity lock | `app/api.py:631-638`, `_run_health_checks` | `tests/test_health.py` |
| Metadata providers | Status and connectivity test | `app/api.py:641-652`, `stager_core/metadata/providers.py` | `tests/test_providers_search.py`, `tests/test_fixture_providers.py`, `tests/test_provider_registry.py` |
| Book discovery | Walk seed tree → `FlatBook` list | `stager_core/discovery.py` | `tests/test_discovery_parts.py`, `tests/test_discovery_parallel.py`, `tests/e2e/test_b_scan.py` |
| Parallel discovery parts | Worker-based discovery | `stager_core/discovery.py` | `tests/test_discovery_parallel.py` |
| Title extraction / cleanup | Modes conservative/balanced/advanced | `stager_core/metadata/title_extraction.py`, `cleanup_pipeline.py` | `tests/test_title_extraction.py`, e2e settings |
| Metadata lookup | Multi-provider search, scoring, fingerprint cache | `stager_core/metadata/lookup.py`, `app/scan.py`, `app/fingerprint_cache.py` | `tests/test_scoring.py`, `tests/test_search_passes.py`, `tests/test_fingerprint.py`, `tests/test_lvi_lookup.py` |
| LVI (library vocabulary) | Match/boost from staged library | `stager_core/metadata/lvi.py`, `library_vocab.py` | `tests/test_lvi_lookup.py`, `tests/e2e/test_h_lvi.py` |
| Series suggestion/scoring | Series fields on candidates | `stager_core/metadata/series_scoring.py` | `tests/test_series_scoring.py`, `tests/test_series_staging.py` |
| Effective metadata / pins | Suggested vs manual vs effective | `stager_core/metadata/effective.py` | `tests/test_effective_metadata.py`, `tests/test_manual_suggested_ux.py`, `tests/test_chosen_pin_migrate.py` |
| Target key preview | UI path preview from draft metadata | `app/api.py:1766-1778` | `tests/test_approve_series_metadata.py` |
| Scan orchestration | Background scan thread, cancel, progress | `app/scan.py` | `tests/test_scan_progress.py`, `tests/test_scan_cancel.py`, `tests/test_scan_dedupe.py`, `tests/test_scan_manual_hints.py`, `tests/test_scan_books_found.py` |
| Session hydration | Persist library index across restart | `app/session.py`, `try_hydrate_from_db` | `tests/test_session_persistence.py`, `tests/test_staging_session.py` |
| Staging / hardlink | Approve, partial, merge stage, unstage | `stager_core/staging.py` | `tests/test_partial_staging.py`, `tests/test_series_staging.py`, `tests/test_bulk_approve.py`, `tests/test_auto_revert.py`, `tests/test_bulk_revert.py` |
| Conflicts | Group detection, library side, resolve | `stager_core/conflicts.py`, `app/api.py` conflicts routes | `tests/test_conflicts.py`, `tests/test_conflict_approve.py`, `tests/e2e/test_e_conflicts.py` |
| Merges | Multi-seed same target | `stager_core/merges.py`, `app/api.py` merge routes | `tests/test_merge_groups.py`, `tests/e2e/test_f_merge.py` |
| Library replace | Remove library files when seed wins same path | `stager_core/staging.py` `replace_library_target` | `tests/test_library_replace.py` |
| Auto-stage | Scan + stage eligible + away queue | `app/auto.py`, `stager_core/auto_eligibility.py` | `tests/test_auto_eligibility.py`, `tests/test_auto_manual_run.py`, `tests/test_manual_approve_review.py`, `tests/test_auto_change_feedback.py` |
| Activity lock | Defer scheduled auto while operator active | `app/activity_lock.py` | `tests/test_activity_lock.py` |
| Decision log | Lookup decisions + operator outcomes | `app/db.py`, `app/api.py` decisions routes | `tests/test_decision_log.py` |
| Destage on rescan | Missing hardlinks → pending | `app/scan.py:559-573` | `tests/test_destage_rescan.py` |
| Duration compare | Seed vs library duration in UI | `stager_core/metadata/duration.py` | `tests/test_duration.py` |
| SQLite schema / migrations | Books, scans, auto, pins migration | `app/db.py` | `tests/test_chosen_pin_migrate.py` |
| Web UI | Full operator workflow | `static/app.js`, `static/index.html` | `tests/e2e/test_a_smoke.py`, `test_c_approve.py`, `test_k_toolbar.py` |
| Docker run | Compose mounts DATA_ROOT, config | `docker-compose.yml`, `README.md` | (no dedicated test observed) |
| Diagnostics tool | LVI CLI | `tools/diagnose_lvi.py` | (no test listed) |

---

## Inference

*Labeled inference — not directly asserted by a single test or UI string.*

1. **“Review”** is not one API action; it is the operator reading partitioned lists and the detail dialog, optionally editing metadata or re-looking-up, before approve/skip/conflict resolution (`static/app.js` + `GET/PATCH` books).
2. **“Destage”** in operator language maps to **unstage/revert** (explicit UI) and **scan-time destage** when library copies disappear (`app/scan.py:559`, `tests/test_destage_rescan.py`).
3. **Conflicts** and **merges** share merge UI machinery (`_perform_merge`, `MergeApprove`) but enter from different API prefixes (`/conflicts/.../merge` vs `/merges/...`).
4. **One library tree** per process: `holder.manager.library_root` and single `StagingSession` (`app/main.py:46-52`).
5. **Approve snapshot**: copying metadata into `chosen_*` without `_set` is intended so staged values are recorded but UI still treats fields as Suggested for relookup (`docs/pinning-model.md:22-24`; inference reinforced by `tests/test_chosen_pin_migrate.py:71-79` on DB reopen, not by approve assertion).

---

## Tests that lock this

| Behavior | Tests |
|----------|--------|
| Flat vs series library paths | `tests/test_series_staging.py`, `tests/test_approve_series_metadata.py` |
| Approve hardlink + DB staged | `tests/e2e/test_c_approve.py`, `tests/test_bulk_approve.py` |
| Unstage/revert | `tests/e2e/test_c_approve.py`, `tests/test_auto_revert.py`, `tests/test_bulk_revert.py` |
| Partial staging lifecycle | `tests/test_partial_staging.py` |
| Scan → discover books | `tests/e2e/test_b_scan.py`, `tests/test_scan_books_found.py` |
| Destage when library links removed | `tests/test_destage_rescan.py` |
| Conflicts detection/exclusions | `tests/test_conflicts.py` |
| Conflict approve API | `tests/test_conflict_approve.py`, `tests/e2e/test_e_conflicts.py` |
| Merge groups + partial merge | `tests/test_merge_groups.py`, `tests/e2e/test_f_merge.py` |
| Auto eligibility (pins block) | `tests/test_auto_eligibility.py` |
| Manual approve dismisses away actions | `tests/test_manual_approve_review.py` |
| Pin revert / effective metadata | `tests/test_manual_suggested_ux.py`, `tests/test_effective_metadata.py` |
| Session fresh/stale/no_scan | `tests/test_session_status.py` |
| Scan cancel | `tests/test_scan_cancel.py` |
| Activity lock | `tests/test_activity_lock.py` |
| Pin migration repair | `tests/test_chosen_pin_migrate.py` |
| E2E smoke | `tests/e2e/test_a_smoke.py` |

**Gap (observed)**: no unit test named for “approve leaves `chosen_*_set` at 0”; contract relies on `docs/pinning-model.md` + SQL shape of `_commit_approve_book` (`app/api.py:1849-1854`).

---

## Single-operator assumptions

1. **No authentication**: FastAPI serves UI and API to whoever can reach the host/port (`app/main.py:22-35`, `80-82`).
2. **One scan at a time**: `ScanAlreadyRunning` (`app/scan.py:188-191`, `app/api.py:802-806`).
3. **One seed root + one library root** per deployment (`app/settings.py:19-24`, `holder.manager` singleton).
4. **One SQLite database** for all book state, scans, auto runs, cache (`app/settings.py:13-16`).
5. **Session lifetime**: in-memory `StagingSession` hydrated from DB on startup when possible; becomes stale after 24h without scan or if not hydrated (`app/session.py:35`, `app/api.py:708-719`).
6. **Personal defaults**: env-specific `BOOKS_ROOT`, `AUDIOBOOKS_ROOT`, `DATA_ROOT`, optional API keys and MAM cookie file under config host (`README.md:17-26`, `.env.example`; paths redacted to variable names only).
7. **Activity lock** assumes a single operator whose clicks postpone scheduled auto (`app/activity_lock.py`, `app/auto.py:94-95`).
8. **Concurrent browsers** not modeled; `DB_LOCK` serializes DB writes but session indexes are process-local.

---

## Unknowns

| Topic | Why unknown | Evidence to read |
|-------|-------------|------------------|
| Full ordered metadata provider chain and failure fallbacks | Not traced line-by-line in this pass | `stager_core/metadata/lookup.py`, `provider_registry.py` |
| Exact conflict/merge dialog field layout and validation messages | Large `static/app.js` surface partially sampled | `static/app.js` conflict/merge render functions |
| Whether conflict approve without body overrides leaves `_set` unchanged after stage | Depends on winner row state before resolve | `app/api.py:1074-1088` + fixture rows in `tests/test_conflict_approve.py` |
| Scheduler timezone / drift edge cases | Only `interval_hours` reschedule observed | `app/scheduler.py` |
| Production MAM cookie rotation semantics | Cookie values must not be documented here | `tests/test_mam_cookie_rotation.py`, `stager_core/metadata` MAM client code |
| `exclude.txt` operator workflow in UI | File-based exclude exists; UI exposure unclear | `stager_core/staging.py:104-118`, config root layout (`stager_core/paths.py`) |