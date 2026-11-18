# Feature inventory (observed)

Each item is what the running app does, or a leftover the reports found in that path. Status is exactly one of **core**, **important**, **scar**, or **unknown**.

A **scar** is a migration leftover, a contradictory path, or a single-operator assumption. Status is only core, important, scar, or unknown. Owner choices are on `OWNER-DECISIONS.md`.

Counts: **16 core**, **19 important**, **13 scar**, **0 unknown**. 48 items.

Evidence cites a rework report plus the `path:line` that report uses. Spot-check lines are marked when a report left the behavior unlabeled.

---

## Core

### F01 Scan

- **Why:** The operator discovers the seed tree, refreshes library inodes, and fills book rows.
- **Evidence:** `01-product-contract.md` workflow “scan a seed folder”; `POST /api/scan` at `app/api.py:785-807`; phases in `app/scan.py:61-63`; writes in `app/scan.py:513+`. UI poll is 1500 ms and also reloads books (`05-ui-workflows.md`, `static/app.js:32`, `static/app.js:4901-4908`).
- **Tests:** `tests/test_scan_progress.py`, `tests/test_scan_books_found.py`, `tests/test_scan_dedupe.py`, `tests/e2e/test_b_scan.py` (`06-test-inventory.md`).
- **Status:** core

### F02 Metadata lookup

- **Why:** A book with tags and a folder name gets suggested author, title, and series from an ordered provider pipeline.
- **Evidence:** `03-metadata-pipeline.md` call order. Entry `MetadataLookupService.resolve_book` (`stager_core/metadata/lookup.py:140-149`). Combined pass order: Audible, MAM, Google Books, Open Library (`lookup.py:210-220`). Title-first order differs (`stager_core/metadata/title_first.py:24-29`). One lookup holds `MetadataLookupService._lock`; provider HTTP inside that lookup is sequential (`03-metadata-pipeline.md`). `POST /api/books/{id}/lookup` does not approve (`01-product-contract.md`, `app/api.py:1781-1788`).
- **Tests:** `tests/test_search_passes.py`, `tests/test_search_context.py`, `tests/test_providers_search.py`, `tests/test_title_first_production.py` (`03-metadata-pipeline.md`, `06-test-inventory.md`).
- **Status:** core

### F03 Scoring, title cleanup, LVI, and oeuvre

- **Why:** Those steps are the product’s suggestion. The metadata report treats their thresholds as behavior that characterization tests already lock.
- **Evidence:** `03-metadata-pipeline.md` section “Heuristic piles that must not be retuned”: `scoring.py` CONFIG (`24-63`, `329+`), `series_scoring.py` CONFIG (`35-56`), `cleanup_pipeline.py` and `title_cleanup.py`, `title_extraction.py` modes, `author_oeuvre.py`, Audible overlap weights (`providers.py:399-421`), LVI floors via `lvi.py:309-310`. LVI search rewrites the query author; LVI boost adds library evidence and does not itself pin (`03-metadata-pipeline.md`, `lvi.py:369-373`, `lookup.py:295-296`). Oeuvre pools Audible author catalog then a MAM author search (`author_oeuvre.py:68-71`).
- **Tests:** `tests/test_scoring.py`, `tests/test_series_scoring.py`, `tests/test_title_extraction.py`, `tests/test_normalize.py`, `tests/test_author_oeuvre.py`, `tests/test_lvi_lookup.py`, `tests/e2e/test_h_lvi.py`.
- **Status:** core

### F04 Pinning

- **Why:** The operator can freeze a field. Effective metadata is the pinned chosen value, otherwise the suggestion. Empty pinned series forces the flat library folder.
- **Evidence:** `01-product-contract.md` metadata model; `docs/pinning-model.md:8-16`; `stager_core/metadata/effective.py:73-98` and `101-107`. `PATCH` sets `_set = 1` for chosen fields present in the body (`app/api.py:1711-1724`). Revert fields clear `_set` (`app/api.py:1699-1710`). Rescan keeps `chosen_*` when `_set = 1` (`03-metadata-pipeline.md`, `app/scan.py:715-729`). Scan manual hints pass pinned author and title only (`app/scan.py:48-57`); series fields exist on the hint type and this helper does not fill them (`03-metadata-pipeline.md`, `stager_core/metadata/types.py:7-11`). UI badges follow `_set` (`01-product-contract.md`, `docs/pinning-model.md:16-17`).
- **Tests:** `tests/test_effective_metadata.py`, `tests/test_manual_suggested_ux.py`, `tests/test_series_patch.py`, `tests/test_scan_manual_hints.py`, `tests/test_chosen_pin_migrate.py`.
- **Status:** core

### F05 Approve

- **Why:** The operator hardlinks one pending book into the library and records the staged metadata on the row.
- **Evidence:** `01-product-contract.md` workflow approve; `POST /api/books/{id}/approve` and bulk (`app/api.py:1889-1929`, `2068+`). Blocked when the book is in a conflict (`app/api.py:1893-1894`). Success sets `status = staged` and copies effective values into `chosen_*` (`app/api.py:1851-1854`). That UPDATE does not touch `chosen_*_set`. See F37 for the other write paths.
- **Tests:** `tests/test_bulk_approve.py`, `tests/test_approve_series_metadata.py`, `tests/e2e/test_c_approve.py`. `06-test-inventory.md` gap: no test asserts `chosen_*_set` after normal approve. `01-product-contract.md` records the same gap.
- **Status:** core

### F06 Skip and unskip

- **Why:** The operator can drop a book from the queue and put it back. Skipped books skip metadata on rescan.
- **Evidence:** `01-product-contract.md`; `POST .../skip` (`app/api.py:2145-2165`); unskip only from `skipped` to `pending` (`app/api.py:2168-2190`). Rescan skip (`app/scan.py:575-578`).
- **Tests:** `tests/e2e/test_c_approve.py` (`test_c_skip_and_unskip_does_not_write_library`). `06-test-inventory.md` also lists skip outcomes in `tests/test_decision_log.py`.
- **Status:** core

### F07 Revert and unstage

- **Why:** The operator removes this book’s library hardlinks and returns the row to pending. The UI label is Unstage. The route is revert.
- **Evidence:** `01-product-contract.md` workflow revert; `POST .../revert` (`app/api.py:2679-2737`); allowed for `staged` or `partial_staged` (`app/api.py:2602-2604`). `unstage_book` unlinks only when `same_inode` (`04-persistence-filesystem.md`, `stager_core/staging.py:735-740`). Foreign inode is `inode_mismatch` and is left in place (`stager_core/staging.py:735-738`). Revert does not clear `chosen_*` or `_set` (`01-product-contract.md`).
- **Tests:** `tests/test_auto_revert.py`, `tests/test_bulk_revert.py`, `tests/e2e/test_c_approve.py`, `tests/test_destage_rescan.py` for the scan-time status reset (F15).
- **Status:** core

### F08 Conflicts

- **Why:** Two pending seeds, or a seed and a library folder, can target one library key. The operator picks a winner or merges.
- **Evidence:** `01-product-contract.md` workflow conflicts; `detect_conflict_groups` (`stager_core/conflicts.py`); refresh in `app/session.py:168-180`. Library side id `LIBRARY_SIDE_ID` (`stager_core/conflicts.py:24`). Library side appears when the target has files and not every source inode is linked (`04-persistence-filesystem.md`, `stager_core/conflicts.py:218-243`). Main approve is blocked while `in_conflict` (`app/api.py:1893-1894`). Conflict approve: library winner skips the seeds; seed winner stages and may call library replace (`app/api.py:1022-1161`, `1089-1094`). Resolutions go to `conflict_resolutions` (`app/api.py:1039-1040`).
- **Tests:** `tests/test_conflicts.py`, `tests/test_conflict_approve.py`, `tests/e2e/test_e_conflicts.py`.
- **Status:** core

### F09 Merges

- **Why:** Two or more pending seeds can share a target key with no library collision and become one staged book.
- **Evidence:** `01-product-contract.md`; `detect_merge_groups` (`stager_core/merges.py:13-57`) skips groups with `has_library_conflict` (`04-persistence-filesystem.md`, `stager_core/merges.py:41-52`). Approve writes combined `files_json`, `status=merged` on members, `book_merges` rows, and one hardlink via `stage_merged_books` (`app/api.py:1409-1468`). UI uses the conflict dialog’s Merge tab (`05-ui-workflows.md`).
- **Tests:** `tests/test_merge_groups.py`, `tests/e2e/test_f_merge.py`.
- **Status:** core

### F10 Partial stage

- **Why:** Some seed files may already be linked at the target. Full stage refuses that case. The operator can link the rest or remove stray library audio.
- **Evidence:** `01-product-contract.md` workflow partial stage; detection `stager_core/staging.py:390-394`, `app/scan.py:536-538`. `stage_book_author_title` returns without linking when analysis says partial (`04-persistence-filesystem.md`, `stager_core/staging.py:390-394`). Complete and remove-extras: `app/api.py:1932-1997`, `2000+`; disk rules `stager_core/staging.py:452-636`. Upsert `ON CONFLICT` preserves `skipped` and `staged` and does not preserve `partial_staged` (`04-persistence-filesystem.md`, `app/scan.py:705-708`).
- **Tests:** `tests/test_partial_staging.py`. `05-ui-workflows.md` and `06-test-inventory.md`: no Playwright file for the partial section.
- **Status:** core

### F11 Auto-stage

- **Why:** On a timer, or on Run now, the process scans and hardlinks pending books that clear a confidence bar and have no pins and no conflict.
- **Evidence:** `01-product-contract.md` workflow auto-stage. Settings `GET/PATCH /api/auto/settings` (`app/api.py:2232-2305`). Run starts a full scan then stages (`app/auto.py:292-327`). Eligibility (`stager_core/auto_eligibility.py:18-37`): pending, not in conflict, no `chosen_*_set`, confidence at least the minimum, author and title present. Inserts `auto_actions`. The auto-stage UPDATE does not set `_set` (`app/auto.py:412-416`). Scheduler: `app/scheduler.py`, `try_scheduled_tick` (`app/auto.py:510-514`).
- **Tests:** `tests/test_auto_eligibility.py`, `tests/test_auto_manual_run.py`, `tests/test_manual_approve_review.py`, `tests/test_auto_change_feedback.py`. `05-ui-workflows.md`: no e2e for the settings dialog or the auto scrim.
- **Status:** core

### F12 Hardlinks and the same-mount precondition

- **Why:** Staging is a hardlink of the seed bytes into the library, so one copy of the audio serves both trees.
- **Evidence:** `os.link` for stage, complete-partial, and merged stage (`04-persistence-filesystem.md`, `stager_core/staging.py:426-427`, `536-537`, `907-908`). Same inode at the destination is a skip (`stager_core/staging.py:415-423`). A different inode at that name is `name_collision` (`stager_core/staging.py:424-437`). README requires the same mount (`README.md:28`). Health checks do not test the mount (`04-persistence-filesystem.md`, `app/api.py:545-628`). E2E helpers compare `st_dev` when they assert a link (`tests/e2e/helpers.py:74`). A path escape guard exists (`06-test-inventory.md`, `stager_core/staging.py:649-655`) and `06` found no test that calls it.
- **Tests:** `tests/test_partial_staging.py`, `tests/test_auto_revert.py`, `tests/e2e/test_c_approve.py`, `tests/test_library_replace.py` (unlink of a hardlink keeps the source). `04-persistence-filesystem.md` unknowns: no unit test for a cross-device `os.link` failure.
- **Status:** core

### F13 Library layout

- **Why:** The library folder is the operator’s shelf order: author, then series, then an indexed title, with a flat author/title folder when the book has no series.
- **Evidence:** `compute_target_key` (`04-persistence-filesystem.md`, `stager_core/staging.py:300-312`). Empty series → `Author/Title` (`staging.py:323-326`). Series present → `Author/Series/{index} - {Title}` (`staging.py:291-297`, `328-332`). Pinned empty series is `confirmed_none` and the preview uses author and title only (`stager_core/metadata/effective.py:152-153`; `01-product-contract.md`, `docs/pinning-model.md:18`). Disk index: 3 path parts read as flat, 4 or more as author/series/title-folder (`04-persistence-filesystem.md`, `stager_core/target_index.py:30-37`). README wording is F36.
- **Tests:** `tests/test_series_staging.py`, `tests/test_series_patch.py`, `tests/test_approve_series_metadata.py`.
- **Status:** core

### F14 Fingerprint identity

- **Why:** The database treats two folders as the same book when the file bytes match, independent of path order.
- **Evidence:** `04-persistence-filesystem.md`. Per file: SHA-256 of size plus 1 MiB head and tail, `ALGO_VERSION = 1` (`stager_core/fingerprint.py:8`, `22-36`). Book id: SHA1 of sorted file fingerprints, first 12 hex chars (`stager_core/fingerprint.py:63-67`, `stager_core/discovery.py:306-310`). Cache hit requires relative path, size, mtime, and algo (`app/fingerprint_cache.py:56-66`). `books.id` is that fingerprint id (`04-persistence-filesystem.md`, `app/db.py:68-94`).
- **Tests:** `tests/test_fingerprint.py` (order, same bytes different path, cache, prune), `tests/test_scan_dedupe.py`, `tests/test_discovery_parallel.py`. `06-test-inventory.md` marks fingerprint identity tested.
- **Status:** core

### F15 Inode staged-or-not

- **Why:** “Already in the library” means the seed inode appears in the library index, including after a restart scan that finds the links gone.
- **Evidence:** `04-persistence-filesystem.md` invariants 2 and 3. Scan sets `staged` / `partial_staged` from `book_already_staged` (`app/scan.py:526-538`). If the row says `staged` and the inodes are gone, scan sets `pending` and clears `staged_path` (`app/scan.py:559-572`). Unstage unlinks only the same inode (F07). `ON CONFLICT` can keep an existing `staged` or `skipped` status (`app/scan.py:705-708`); the destage guard is the path that clears a staged row whose links disappeared (`04-persistence-filesystem.md` inference).
- **Tests:** `tests/test_destage_rescan.py`, `tests/test_target_index.py`, `tests/test_staging_session.py`, `tests/test_auto_revert.py`.
- **Status:** core

### F16 One scan and one auto-run

- **Why:** The process has one scan thread and one auto thread, and each refuses to start while the other is alive.
- **Evidence:** `02-backend-boundaries.md` one-at-a-time rules. `ScanAlreadyRunning` (`app/scan.py:279-282`, `app/api.py:802-806`). `POST /api/scan` 409 if auto is running (`app/api.py:789-798`). `AutoRunBlocked` if a scan is alive (`app/auto.py:113-115`). Scheduler job `max_instances=1` (`app/scheduler.py:15-28`). The auto workflow starts the scan thread inside itself (`02-backend-boundaries.md`, `app/auto.py` near 298). This is also listed as a single-operator assumption in `01-product-contract.md` and `08-scale.md`. The exclusion itself is enforced in code, so the status stays core.
- **Tests:** `tests/test_scan_cancel.py` covers cancel of the one scan. `tests/test_auto_manual_run.py` covers the activity lock versus scheduled auto, which is F18. `06-test-inventory.md` gap: no test of overlapping approve and scan.
- **Status:** core

---

## Important

### F17 Session hydration

- **Why:** A restart within a day of the last finished scan rebuilds the in-memory library index from SQLite instead of walking the library again.
- **Evidence:** `02-backend-boundaries.md` session section. `STALE_SCAN_HOURS = 24` (`app/session.py:35`). Hydrate requires a parseable `last_scan_finished_at` inside 24 hours, `count_books > 0`, and a non-empty `library_targets` (`app/session.py:253-277`). Otherwise startup builds a stale session (`app/main.py:48-51`). API returns 409 when the session is not ready or is stale (`app/api.py:265-272`).
- **Tests:** `tests/test_session_persistence.py`, `tests/test_session_status.py`, `tests/test_staging_session.py`.
- **Status:** important

### F18 Activity lock

- **Why:** Clicks postpone scheduled auto-stage so a running operator is not raced by the timer.
- **Evidence:** `01-product-contract.md`; `renew_activity_lock` extends `locked_until` by `lock_timeout_minutes` (`app/activity_lock.py:13-33`). Scheduled path checks the lock (`app/auto.py:94-95`, `121-122`). Manual run may pass `bypass_activity_lock=True` (`app/auto.py:103`, `app/api.py:2431+`). One row, `activity_lock.id = 'default'` (`02-backend-boundaries.md`, `app/db.py:737-741`). Settings copy says the same thing (`05-ui-workflows.md`, `static/index.html:263-264`). The write path that skips `DB_LOCK` is F46.
- **Tests:** `tests/test_activity_lock.py`, `tests/test_auto_manual_run.py`. `06-test-inventory.md` gap: no concurrent approve-plus-scan test.
- **Status:** important

### F19 Credentialed providers

- **Why:** Google Books and MyAnonaMouse can add candidates when a key or session id is present. When it is absent, those searches return no candidates and the rest of lookup still runs.
- **Evidence:** `03-metadata-pipeline.md` provider table. Google: `if not self.google_api_key: return []` (`stager_core/metadata/providers.py:718-720`), env `GOOGLE_BOOKS_API_KEY`. MAM: `if not self.mam_id: return []` (`providers.py:490-492`). Registry marks both disabled when unset (`provider_registry.py:29-45`, `07-oss-readiness.md`). They stay registered (`provider_registry.py:10-11`). Signed policy is D02. The status-versus-lookup split for MAM is F42.
- **Tests:** `tests/test_provider_registry.py` (key-gated list, probe skips unconfigured Google), `tests/test_providers_search.py`, `tests/test_scan_books_found.py:30-44`.
- **Status:** important

### F20 Keyless providers and contact email

- **Why:** Audnexus, Audible, and Open Library run without an API key. Open Library’s contact string is a User-Agent identity.
- **Evidence:** `03-metadata-pipeline.md` and `07-oss-readiness.md`. Registry `requires_key: False` for audnexus, audible, openlibrary (`provider_registry.py:7-9`). They stay enabled when keys are unset (`tests/test_provider_registry.py:28-36`). Audnexus runs when the context has an ASIN (`lookup.py:271-272`). `METADATA_CONTACT_EMAIL` is composed into the User-Agent and does not gate Open Library (`03-metadata-pipeline.md`, `lookup.py:82-88`, `providers.py:652-685`). Unset, the contact token in that User-Agent is the literal `local-dev` (`07-oss-readiness.md`, `lookup.py:82-83`). `07` infers that a blank value takes the same fallback. Empty keys are not an offline mode; live HTTP still runs unless `STAGER_METADATA_BACKEND=fixture` (`07-oss-readiness.md`, `lookup.py:100-111`).
- **Tests:** `tests/test_provider_registry.py`, `tests/test_providers_search.py`, `tests/test_fixture_providers.py` for the fixture switch.
- **Status:** important

### F21 While you were away

- **Why:** Books the auto-run staged are listed for Okay or Revert.
- **Evidence:** `01-product-contract.md`; `GET /api/auto/review` (`app/api.py:2467+` in `05-ui-workflows.md`). UI: `static/app.js:4298-4305`, dismiss `POST /api/auto/review/dismiss`. **Spot-check:** the handler selects undismissed `auto_actions` with `action = 'staged'` and no `LIMIT` (`app/api.py:2467-2498`), which closes the pagination unknown in `05-ui-workflows.md`. `GET /api/auto/feedback` is paged (`app/api.py:2547-2551`) and `05` found no caller in `static/app.js`.
- **Tests:** `tests/test_auto_change_feedback.py` (feedback list `limit`/`offset`, dismiss, revert), `tests/test_manual_approve_review.py`. No e2e (`05-ui-workflows.md`).
- **Status:** important

### F22 Decision log

- **Why:** Lookup choices and operator outcomes are stored for later inspection.
- **Evidence:** `01-product-contract.md` feature table; `lookup_decisions` and `decision_outcomes` (`04-persistence-filesystem.md`, `app/db.py:96-283`). Approve writes `action=approve` (`01-product-contract.md`, `app/api.py:1835-1886`).
- **Tests:** `tests/test_decision_log.py`.
- **Status:** important

### F23 Duration compare

- **Why:** Conflict and detail views can show seed duration against library duration.
- **Evidence:** `01-product-contract.md`; `stager_core/metadata/duration.py`; routes in `05-ui-workflows.md` (`GET /api/books/{id}/duration`, conflict duration).
- **Tests:** `tests/test_duration.py`.
- **Status:** important

### F24 Health

- **Why:** One endpoint reports database, scan, library paths, and the activity lock.
- **Evidence:** `01-product-contract.md`; `app/api.py:631-638`. Degraded when `DB_LOCK` is not acquired in time (`02-backend-boundaries.md`, `app/api.py:557-563`).
- **Tests:** `tests/test_health.py`, `tests/e2e/test_a_smoke.py`.
- **Status:** important

### F25 Bulk approve, unskip, and revert

- **Why:** The staging toolbar applies one action to the current selection.
- **Evidence:** `05-ui-workflows.md` staging list; `POST /api/books/bulk-approve`, `bulk-unskip`, `bulk-revert` (`static/app.js:5302-5318`). Server uses a thread pool for bulk work (`02-backend-boundaries.md`, `app/api.py:1825`, `2637`).
- **Tests:** `tests/test_bulk_approve.py`, `tests/test_bulk_revert.py`, `tests/e2e/test_c_approve.py` (bulk approve). `05-ui-workflows.md` gap: no e2e for bulk unstage or bulk unskip.
- **Status:** important

### F26 Library replace helper

- **Why:** When a seed wins a conflict against a library folder, the process can unlink library audio at a target before linking the seed. The path it computes is F41.
- **Evidence:** `04-persistence-filesystem.md` table row “Replace library target”; `replace_library_target` unlinks audio under the resolved directory, leaves non-audio, prunes empty dirs (`stager_core/staging.py:657-697`). Called from conflict approve (`app/api.py:1089-1094`).
- **Tests:** `tests/test_library_replace.py`, `tests/test_conflict_approve.py` (`test_approve_seed_over_library_replaces_and_stages`). Neither report shows a series-folder case for this helper.
- **Status:** important

### F27 Unmerge API

- **Why:** An API can unstage a merged primary and split the member files back apart.
- **Evidence:** `01-product-contract.md`; `DELETE /api/merges/{primary}` (`app/api.py:1553-1612`). `05-ui-workflows.md`: the static client does not call that route.
- **Tests:** `tests/test_merge_groups.py` covers merge API stage and related helpers (`06-test-inventory.md`). `06` does not name a dedicated unmerge assertion; treat unmerge UI coverage as absent per `05`.
- **Status:** important

### F28 Fixture metadata backend

- **Why:** Tests and e2e replace live provider HTTP with a catalog, so the suite can run without those networks.
- **Evidence:** `03-metadata-pipeline.md`; `STAGER_METADATA_BACKEND=fixture` (`stager_core/metadata/fixture_providers.py:118-119`, `lookup.py:100-101`). E2E sets it (`06-test-inventory.md`, `tests/e2e/conftest.py:61`). Default unit pytest does not set it globally (`06-test-inventory.md`).
- **Tests:** `tests/test_fixture_providers.py`. Provider unit tests use in-memory fakes (`tests/test_providers_search.py`).
- **Status:** important

### F29 Schema migration and false-pin repair

- **Why:** Opening the database adds missing columns and, once, clears pin flags whose chosen text equals the suggestion.
- **Evidence:** `04-persistence-filesystem.md`; `_migrate_schema` on every `connect` via `PRAGMA table_info` (`app/db.py:300-441`). `schema_flags` key `repair_false_chosen_pins_v1` (`app/db.py:469-494`). No version table beyond those flags (`02-backend-boundaries.md`).
- **Tests:** `tests/test_chosen_pin_migrate.py`. `06-test-inventory.md` gap: no checked-in legacy database that replays the full ALTER chain.
- **Status:** important

### F30 Static operator UI

- **Why:** The whole operator workflow is one HTML page, dialogs, and `fetch` to `/api`.
- **Evidence:** `05-ui-workflows.md`. Served at `/` (`app/main.py:80`). No `location.hash` or `history.pushState`. Sections: away, conflicts, partial, staging. Parity checklist is in that report. localStorage holds sort, section collapse, confirm suppression, and the finish-scan animation flag.
- **Tests:** `tests/e2e/test_a_smoke.py`, `test_b_scan.py`, `test_c_approve.py`, `test_e_conflicts.py`, `test_f_merge.py`, `test_h_lvi.py`, `test_k_toolbar.py`. Gaps listed in `05-ui-workflows.md`: partial UI, away review, settings, provider chip text, detail PATCH, auto cancel.
- **Status:** important

### F31 Metadata API cache

- **Why:** Provider responses, including some failures, are stored so a rescan does not repeat the same HTTP immediately.
- **Evidence:** `03-metadata-pipeline.md` failure-caching table; `stager_core/metadata/cache.py:13-63`. Clear: `POST /api/auto/cache/clear` deletes `api_cache` and sets `cache_relookup_pending` (`01-product-contract.md`, `app/api.py:2455-2464`).
- **Tests:** `06-test-inventory.md` does not name a dedicated cache-clear test. Provider tests use `FakeCache` (`tests/test_providers_search.py`).
- **Status:** important

### F32 Scan cancel

- **Why:** The operator can stop a running scan; a cancelled rescan is specified to leave books and seed files in place.
- **Evidence:** `05-ui-workflows.md`; `POST /api/scan/{id}/cancel` (`static/app.js:901-919`).
- **Tests:** `tests/test_scan_cancel.py`, `tests/e2e/test_b_scan.py` (`test_b_rescan_cancel_keeps_books_and_seeds`). `06-test-inventory.md` marks scan cancel tested.
- **Status:** important

### F33 Discovery

- **Why:** The seed walk decides which files form one book, including multi-file parts, before any metadata call.
- **Evidence:** `01-product-contract.md` feature table; `stager_core/discovery.py` (337 lines in `02-backend-boundaries.md`). Parallel discovery is worker-based (`02-backend-boundaries.md`, `stager_core/discovery.py:221`).
- **Tests:** `tests/test_discovery_parts.py`, `tests/test_discovery_parallel.py`, `tests/e2e/test_b_scan.py`.
- **Status:** important

### F34 Manual hints and target preview

- **Why:** Pinned author and title can steer the next lookup, and the detail form shows the folder that the current draft would use.
- **Evidence:** Hints: `01-product-contract.md`, `app/scan.py:48-57`, `docs/pinning-model.md:37-39`. Re-lookup by id uses pins regardless of the scan setting (`06-test-inventory.md`, `tests/test_scan_manual_hints.py`). Preview: `POST /api/books/{id}/target-key-preview` (`05-ui-workflows.md`, `app/api.py:1766-1778`).
- **Tests:** `tests/test_scan_manual_hints.py`, `tests/test_series_patch.py` (`test_target_key_preview_endpoint`). No e2e focused on detail PATCH (`05-ui-workflows.md`).
- **Status:** important

### F35 Docker single service

- **Why:** The documented run path is one container with one data mount and one config mount.
- **Evidence:** `07-oss-readiness.md` packaging table; `Dockerfile:1-16`; `docker-compose.yml:1-36` service `audiobook-stager`. `01-product-contract.md`: no dedicated Docker test observed. E2E starts `uvicorn app.main:app` on localhost (`06-test-inventory.md`, `tests/e2e/conftest.py:82-112`).
- **Tests:** none named for Compose.
- **Status:** important

---

## Scar

### F36 README layout wording

- **Why:** Three public sentences describe the library folders differently. The code builds both the flat path and the series path (F13).
- **Evidence:** `01-product-contract.md` table “README vs UI vs code”, repeated in `07-oss-readiness.md` doc contradictions. `README.md:3` says `Author/Title`. `static/index.html:13` says `Author/Series/Title/`. `stager_core/staging.py:307-312` builds both. `docs/pinning-model.md:18` documents flat when series is pinned empty.
- **Tests:** layout tests lock the code (F13). No test locks the README sentence.
- **Status:** scar

### F37 Conflict and merge pin flags versus normal approve

- **Why:** Normal approve stores a staging snapshot and leaves pin flags alone. Conflict save, and conflict or merge approve when the body carries overrides, set all four pin flags.
- **Evidence:** `01-product-contract.md` section “Pinning: normal approve vs conflict/merge paths” and `03-metadata-pipeline.md` mismatch table. Normal approve UPDATE omits `_set` (`app/api.py:1851-1854`). `save_conflict_edits` sets all four `_set = 1` (`app/api.py:996-997`). `approve_conflict` does that only when `has_overrides` (`app/api.py:1074-1082`). The post-stage UPDATE on that path also omits `_set` (`03-metadata-pipeline.md`, `app/api.py:1110-1115`). Merge approve matches the override pattern (`app/api.py:1426-1433`). `01` still marks the resulting flags unknown when the row was already pinned before a no-override approve. Both reports agree the no-override SQL does not write `_set`. Auto-stage then skips any book with any `_set` (`stager_core/auto_eligibility.py:27-32`).
- **Tests:** `06-test-inventory.md` gap “Pin flags: conflict approve vs merge approve vs normal approve” is untested as a distinction. `tests/test_conflict_approve.py` locks override stage, save-edits, and library replace, and does not assert `_set` (`06`).
- **Status:** scar

### F38 Unbounded list and conflict reads

- **Why:** The page asks for every partition in one response. The server reads the whole `books` table to build it. That matches a single operator with a small library, and it is the cost `08-scale.md` measures.
- **Evidence:** `08-scale.md`. `list_books` runs `SELECT * FROM books ORDER BY source_path` (`app/api.py:229-233`). Conflict refresh and merge refresh each run that read again: three full reads per list (`app/api.py:882`, `app/session.py:168-192`). Filters for status and `q` run in Python (`app/api.py:810-866`). Partitioned mode slices `staging` with default `limit=500` (`app/api.py:907`) and returns all of `partial`, `conflicts`, and `merges` (`app/api.py:894-908`). The UI sends `partitioned=true` and no `limit` or `offset` (`05-ui-workflows.md`, `static/app.js:4788-4795`), renders every partial, conflict, and merge row (`05-ui-workflows.md` unbounded table), and calls `loadBooks` on every 1.5 s scan poll. Away review is the same shape (F21 spot-check). `08-scale.md` inference: about 150,000 row-equivalents per `list_books` at 50,000 books.
- **Tests:** `06-test-inventory.md` gap: no test references `limit`/`offset` on `/api/books`. `08-scale.md`: no test locks the 500 cap or a cap on conflicts or partials.
- **Status:** scar

### F39 Provider registry versus `providers.py`

- **Why:** A small catalog reports enabled and configured. All search HTTP, caching, and the MAM client still live in the 919-line provider module. Probe constants are duplicated.
- **Evidence:** `02-backend-boundaries.md` section “`provider_registry.py` versus `providers.py`”. Registry is 76 lines: `PROVIDER_DEFS` (`provider_registry.py:6-12`), `list_provider_status` (`29-45`), probes delegate to `MetadataProviders.probe_connectivity` (`48-75`). `providers.py` holds env load, MAM id resolution, and `MetadataProviders` (`217+`, probe `850+`). Duplicate `_PROBE_*` at `providers.py:916-918` and `provider_registry.py:14-16`. Lookup imports both (`lookup.py:29-35`). `03-metadata-pipeline.md`: lookup skips use the inline guards, not `list_provider_status`.
- **Tests:** `tests/test_provider_registry.py`, `tests/test_providers_search.py`, `tests/test_fixture_providers.py`.
- **Status:** scar

### F40 `research` import guard with no `research` package

- **Why:** A test forbids `app/` and `stager_core/` from importing `research`. The workspace has no `research` package.
- **Evidence:** `02-backend-boundaries.md`; `tests/test_no_research_imports_in_stager.py:9-12`. Glob on 2026-11-17 found no `research/` directory. `02` infers the guard is forward-looking.
- **Tests:** `tests/test_no_research_imports_in_stager.py`.
- **Status:** scar

### F41 `replace_library_target` path shape

- **Why:** Conflict approve decides the library key with series included, then deletes and forgets a key built from author and title only.
- **Evidence:** `04-persistence-filesystem.md` inference and unknowns table called the 3-level outcome unknown and cited `app/session.py:127`, `stager_core/staging.py:657-659`, `app/api.py:1091`. **Spot-check of those lines:** `replace_library_target(library_root, author, title)` calls `resolve_staging_target(library_root, author, title)` (`stager_core/staging.py:657-659`). With empty series that resolves `library/Author/Title` (`staging.py:323-326`). The series form is a different directory (`staging.py:328-332`). The unlink loop is `rglob` of audio under that resolved directory (`staging.py:684-688`). If the directory is missing, the function returns `replaced` and removes nothing (`staging.py:677-680`). Conflict approve computes `staging_key` with series (`app/api.py:1089`) and, when that key equals the group key and a library side exists, calls `replace_library_target(..., author, title)` (`app/api.py:1091`) and `apply_replace_library(author, title)` (`app/api.py:1094`). Session drop uses `compute_target_key(author, title)` (`app/session.py:126-128`) and returns immediately when that flat key is absent (`app/session.py:128-130`). The following `stage_book_author_title` call does receive series (`app/api.py:1096-1105`). `01-product-contract.md` names the replace call and does not describe this path split. The two reports do not contradict; `04` left the series outcome unlabeled, and the cited functions do not take series.
- **Tests:** `tests/test_library_replace.py` locks the helper’s audio unlink and non-audio keep (`04`, `06`). No report shows a test whose library folder is `Author/Series/Title`.
- **Status:** scar

### F42 MAM status versus lookup resolver

- **Why:** The provider list and the lookup constructor do not ask the same function whether MAM is configured.
- **Evidence:** `07-oss-readiness.md` inference 2, grounded in `provider_registry.py:22-25` (`resolve_stager_mam_id`) versus `lookup.py:92` (`resolve_mam_id`, wired at `lookup.py:92-110`). **Spot-check:** `list_provider_status` uses `resolve_stager_mam_id()` for the MAM env key (`provider_registry.py:22-25`); `MetadataLookupService` sets `mam_id = resolve_mam_id()` (`lookup.py:92`) and passes it into `MetadataProviders` (`lookup.py:104-110`). `03-metadata-pipeline.md` documents the wider lookup resolution and the inline empty-id skip (`providers.py:490-492`). `07` infers the status UI can show MAM disabled while lookup still holds an id from the wider resolver. Search still returns no rows when the id that reached the provider is empty.
- **Tests:** `tests/test_provider_registry.py` locks the registry flag. `tests/test_mam_cookie_rotation.py` locks cookie extract and persist on the provider object (`06-test-inventory.md`). No report shows a test that the status flag and `resolve_mam_id()` agree.
- **Status:** scar

### F43 `exclude.txt` helpers with no callers

- **Why:** The staging module can read a config-root file of paths to skip. Nothing in the application calls that reader.
- **Evidence:** `01-product-contract.md` unknowns: file-based exclude exists, UI exposure unclear, cited `stager_core/staging.py:104-118`. **Spot-check:** `load_staging_excludes` and `is_excluded` are defined at `stager_core/staging.py:104-119`. A search of `*.py` found no other reference. A search of `static/` found no `exclude.txt`. A search of `tests/` found no matches. Whether a deployment still has the file on disk is unknown (`01` unknowns). The code path that would read it has no caller.
- **Tests:** none found.
- **Status:** scar

### F44 `mam_exact` scoring prior

- **Why:** Scoring has a family prior and a confidence floor for an exact MAM match. Application code does not emit that family.
- **Evidence:** `03-metadata-pipeline.md` unknowns: no non-test producer; `scoring.py:39`. **Spot-check of `*.py`:** the prior is `FAMILY_PRIORS["mam_exact"]` with the comment “Phase 2 (exact infohash match)” (`stager_core/metadata/scoring.py:39`). If the family is present, confidence is raised to `MAM_EXACT_FLOOR` (`scoring.py:321-323`). The only other `*.py` hit is `tests/test_scoring.py:55` (`test_mam_exact_alone`). `03` said a wider search would be needed for infohash wiring; this search covered Python sources and found no emitter outside scoring and that test.
- **Tests:** `tests/test_scoring.py` locks the floor when the family is supplied. It does not lock a producer.
- **Status:** scar

### F45 `library_cache` imports the holder

- **Why:** Domain code reaches into the FastAPI module to reuse the live session’s indexes.
- **Evidence:** `02-backend-boundaries.md` cross-cutting seam. Lazy `from app.api import holder` (`stager_core/library_cache.py:17`, also `55`, `69`). `invalidate_library_cache` sets `holder.session` stale (`library_cache.py:67-73`). Import failure is caught so tools can call core without the app (`library_cache.py:23-24`). `08-scale.md`: if the session is not ready, `get_library_indexes` walks the library twice.
- **Tests:** `tests/test_library_cache.py`.
- **Status:** scar

### F46 Activity-lock write outside `DB_LOCK`

- **Why:** Most mutations take `DB_LOCK` before using the shared connection. Renewing the activity lock commits on that connection without taking it.
- **Evidence:** `02-backend-boundaries.md` SQLite section; `renew_activity_lock` (`app/activity_lock.py:20-28`). Callers in `app/api.py` often already hold `DB_LOCK` via `_renew_lock` (`app/api.py:512-513`). `02` unknowns: the full set of `commit()` paths without `DB_LOCK` was only partly reviewed; this one is confirmed.
- **Tests:** `tests/test_activity_lock.py` locks renew, expiry, and the default timeout. It does not lock lock-ordering against `DB_LOCK`.
- **Status:** scar

### F47 Personal defaults in the public tree

- **Why:** A fresh clone’s examples encode one operator’s directories, timezone, and product string.
- **Evidence:** `07-oss-readiness.md` personal-data table, classification “Must become optional config”: default `BOOKS_ROOT` `/data/Dropbox/Books` (`stager_core/paths.py:11`, `.env.example:10`, `docker-compose.yml:13`); default `AUDIOBOOKS_ROOT` `/data/Audiobooks`; `TZ=America/Denver` (`.env.example:8`, `docker-compose.yml:12`); User-Agent `SeedboxAudiobookStager/0.1` (`lookup.py:82-83`). Repo `.env` autoload for research keys (`providers.py:35-66`). Fallback cookie paths under `CONFIG_ROOT` are in that same table. This inventory does not repeat how a session id is obtained.
- **Tests:** none named for the example defaults. `tests/test_provider_registry.py` and `tests/test_mam_cookie_rotation.py` use synthetic paths (`07-oss-readiness.md`).
- **Status:** scar

### F48 No authentication

- **Why:** The process assumes one operator on a trusted host. Anyone who can reach the port can call the API and use the page.
- **Evidence:** `01-product-contract.md` single-operator assumptions; `app/main.py:22-35`, `80-82`. `05-ui-workflows.md`: `fetch` in `api()` sends no credentials (`static/app.js:1268-1293`). No auth UI. Concurrent browsers are not modeled; `DB_LOCK` serializes writes and session indexes are process-local (`01-product-contract.md`).
- **Tests:** `06-test-inventory.md` lists no auth test. E2E talks to localhost uvicorn (`tests/e2e/conftest.py`).
- **Status:** scar

---

## Not given an id

These stay unknown and are not features to classify:

| Topic | Where |
| --- | --- |
| Uvicorn worker count in production | `02-backend-boundaries.md` unknowns |
| Scheduler timezone drift | `01-product-contract.md` unknowns |
| `candidates_json` size, 50,000-book conflict counts, peak RSS | `08-scale.md` unknowns |
| `st_ino` where inodes are not stable | `04-persistence-filesystem.md` unknowns |
| Clean-clone pytest result; Docker health before data directories exist | `07-oss-readiness.md` unknowns |
| Legal text | No `LICENSE` file (`07-oss-readiness.md`). Noted on `OWNER-DECISIONS.md`. Not a feature row |
