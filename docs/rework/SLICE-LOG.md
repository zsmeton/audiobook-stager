# Slice log

## S1 Settings and public config

- **Slice id:** S1
- **Files changed:** `app/settings.py`, `stager_core/paths.py`, `.env.example`, `docker-compose.yml`, `tests/test_settings_defaults.py`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `Dockerfile` (no `TZ` introduced), `README.md` (no new variable), `stager_core/metadata/**`, `app/api.py`, `static/`, `stager_core/discovery.py`
- **Tests run:** `py -3 -m pytest` — 348 passed, 5 skipped (3 D05, 2 D07), 13 e2e deselected. No network.
- **Remaining risks:** `stager_core.paths` raises until `app.settings` is imported, so `stager_core` still does not import `app`. Unset Python defaults are cwd-relative `./data/seeds` and `./data/library`; Compose injects container paths `/data/seeds` and `/data/library`. Provider env reads, the User-Agent string, and rate-limit numbers stay in the metadata modules. Cookie-file fallbacks and repo `.env` autoload stay in `providers.py`. README does not mention `TZ`; `.env.example` and Compose default it to `UTC`.

## S2 SQLite repositories

- **Slice id:** S2
- **Files changed:** `app/db.py`, `app/repositories/__init__.py`, `app/repositories/books.py`, `app/api.py`, `app/session.py`, `tests/test_d07_bounded_lists.py`, `docs/rework/SLICE-LOG.md`
- **Tests run:** `py -3 -m pytest` — 350 passed, 3 skipped (D05), 13 e2e deselected. No network. D07 classes are unskipped, including the 50,000-row SQL insert.
- **Remaining risks:** Conflict and merge detection still loads every eligible book (not staged, skipped, partial, or merged) once per refresh. The payload is capped; that read is not. `GET /api/books` with no `limit` uses 500 for staging, partial, conflicts, and merges, and the current page has no pager, so section badges follow the page while status chips still count the table. Merge members whose group is past that cap can show in staging, because the page only hides members of the merges it received. Library-only conflicts stay out of staging. Search uses SQLite `lower`/`trim` and the first `candidates_json` object for series. Partial promotion during a list runs only for the returned partial page.

## S3 Services out of app/api.py

- **Slice id:** S3
- **Files changed:** `app/api.py`, `app/main.py`, `app/routers/health.py`, `app/routers/scan.py`, `app/routers/books.py`, `app/routers/conflicts.py`, `app/routers/merges.py`, `app/routers/auto.py`, `app/services/health.py`, `app/services/scan.py`, `app/services/books.py`, `app/services/conflicts.py`, `app/services/merges.py`, `app/services/auto.py`, `docs/rework/SLICE-LOG.md`
- **Tests run:** `py -3 -m pytest` — 350 passed, 3 skipped (D05), 13 e2e deselected. No network. No test file edited.
- **Remaining risks:** `/metadata/providers`, `/metadata/providers/test`, `/session/status`, `/settings/title-extraction/preview`, and `/decisions` stay on the router in `app/api.py`. Pin-flag writes are unchanged (D05 is S6). List, conflict, and merge SQL stays in `app/repositories/books.py`. `list_books` still refreshes every eligible book via `_compute_conflicts`, then reads cached merges. Book helpers and the shared conflict/merge lock live in `app/services/books.py`. Each service imports `holder` last so `app/api` can re-export names while that module is loading; moving those imports to the top brings the cycle back. `app/scan.py` still imports `_maybe_reconcile_partial_row` from `app.api`.

## S4 Providers

- **Slice id:** S4
- **Files changed:** `stager_core/metadata/providers.py`, `stager_core/metadata/provider_registry.py`, `stager_core/metadata/lookup.py`, `stager_core/metadata/audnexus.py`, `stager_core/metadata/audible.py`, `stager_core/metadata/openlibrary.py`, `stager_core/metadata/google_books.py`, `stager_core/metadata/mam.py`, `tests/test_empty_key_skip.py`, `docs/rework/SLICE-LOG.md`
- **Tests run:** `py -3 -m pytest` — 354 passed, 3 skipped (D05), 13 e2e deselected. No network. `tests/test_fitness_boundaries.py` was not edited and passed.
- **Remaining risks:** The empty-key decision is `empty_key_blocks` in `provider_registry.py`. Lookup's external pass calls `invoke_provider`. Google Books and MAM search and probe pass their instance credential into that predicate. Registry status for MAM still uses `resolve_stager_mam_id` (cookie file, then `STAGER_MAM_ID`). Lookup stores `resolve_mam_id`, which also reads `MAM_ID` and `MAM_COOKIE_FILE`, so status and search can disagree when only that fallback is set. Title-first and author-oeuvre call provider methods directly; Google and MAM still consult the predicate there, and a later provider is skipped only when its caller uses the registry gate. Cookie-file fallbacks and repo `.env` autoload now live in `mam.py`. Rate-limit numbers stay in `ratelimit.py`.

## S5 Metadata modules

- **Slice id:** S5
- **Files changed:** `stager_core/metadata/title_matching.py`, `stager_core/metadata/cleanup_pipeline.py`, `stager_core/metadata/library_vocab.py`, `stager_core/metadata/title_cleanup.py`, `stager_core/metadata/series_scoring.py`, `docs/rework/SLICE-LOG.md`
- **Tests run:** `py -3 -m pytest` — 354 passed, 3 skipped (D05), 13 e2e deselected. No network. No test file edited. Diff is deletions only.
- **Remaining risks:** Removed helpers had no callers and no test names. `_EMPTY_CLUSTER_KEY` (`"__none__"`) in `series_scoring.py` is now unread; it was left because it is a string constant, not a helper. Clustering still uses `series_sim`. Scoring weights, cleanup step order, LVI thresholds, and D02 skip behavior are unchanged. Helpers still called inside their own module were kept.

## S6 Staging, conflicts, merges

- **Slice id:** S6
- **Files changed:** `stager_core/staging.py`, `stager_core/conflicts.py`, `app/services/conflicts.py`, `app/services/merges.py`, `docs/pinning-model.md`, `tests/test_pin_flag_writes.py`, `tests/test_d05_pin_flags.py`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `stager_core/merges.py` (grouping), `app/services/books.py` (normal approve), `app/session.py` (`apply_replace_library`), `tests/test_library_replace.py`, `tests/test_library_root_guard.py`
- **Tests run:** `py -3 -m pytest` — 358 passed, 0 skipped, 13 e2e deselected. No network. D05 classes are unskipped. `tests/test_library_replace.py` and `tests/test_library_root_guard.py` passed without edits.
- **Remaining risks:** `apply_replace_library` still forgets only the flat `Author/Title` key. A series replace unlinks the series directory, and the series side can stay in the session index and in `library_targets` until the next rebuild. Conflict detection checks those files on disk, so a resolved group does not come back from the stale rows alone. Conflict save-edits always receives all four fields, so an omitted series is an empty series edit. `docs/rework/HARNESS.md` still describes the old all-four pin writes and the D05 skip. Normal approve still leaves flags unchanged, in `app/services/books.py`.

## S7 App state

- **Slice id:** S7
- **Files changed:** `app/main.py`, `app/api.py`, `app/activity_lock.py`, `app/routers/health.py`, `app/routers/scan.py`, `app/routers/books.py`, `app/routers/conflicts.py`, `app/routers/merges.py`, `app/routers/auto.py`, `app/services/health.py`, `app/services/scan.py`, `app/services/books.py`, `app/services/conflicts.py`, `app/services/merges.py`, `app/services/auto.py`, `stager_core/library_cache.py`, `tests/test_pin_flag_writes.py`, `tests/test_d05_pin_flags.py`, `tests/test_d07_bounded_lists.py`, `tests/test_scan_cancel.py`, `tests/test_series_patch.py`, `tests/test_decision_log.py`, `tests/test_health.py`, `tests/test_conflict_approve.py`, `tests/test_manual_approve_review.py`, `tests/test_approve_series_metadata.py`, `tests/test_bulk_approve.py`, `tests/test_fitness_boundaries.py`, `tests/test_auto_change_feedback.py`, `tests/test_manual_suggested_ux.py`, `tests/test_activity_lock_exclusion.py`, `tests/test_session_status.py`, `tests/test_merge_groups.py`, `tests/test_bulk_revert.py`, `docs/rework/SLICE-LOG.md`
- **Tests run:** `py -3 -m pytest` — 358 passed, 0 skipped, 13 e2e deselected. No network. Pin-flag and D07 assertions were not changed. Fitness allowlist for `library_cache` is empty.
- **Remaining risks:** Routes that stayed in `app/api.py` (`/metadata/providers`, `/session/status`, title-extraction preview, `/decisions`) read `app.api.holder` directly; that name is the startup object. Each service keeps a proxy bound to that same object when `app.main` loads. A test that binds `from app.api import holder` before `app.main` runs still sees `None`. `get_activity_lock` still reads without `DB_LOCK`; only `renew_activity_lock` takes it. `stager_core/paths.py` and `docs/rework/HARNESS.md` still say `library_cache` may import `app`. Session index reuse happens only after `app.main` registers the session provider.

## S8 API contract

- **Slice id:** S8
- **Files changed:** `tests/test_openapi_pagination.py`, `docs/rework/API.md`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `app/main.py` (`FastAPI(title="Audiobook Stager", version="0.1.136")` was already explicit), `app/routers/health.py`, `app/routers/scan.py`, `app/routers/books.py`, `app/routers/conflicts.py`, `app/routers/merges.py`, `app/routers/auto.py` (registered handlers already declare the query parameters OpenAPI publishes), `app/services/**`, `static/`
- **Tests run:** `py -3 -m pytest` — 362 passed, 0 skipped, 13 e2e deselected. No network. No listening port. `tests/test_openapi_pagination.py` reads `app.openapi()`.
- **Remaining risks:** `GET /api/conflicts`, `GET /api/merges`, and `GET /api/auto/review` publish no query parameters; those handlers return the whole list. `GET /api/books` still uses `limit` 500 when the client omits it. `docs/rework/API.md` is a snapshot of this schema, and the test checks the live schema rather than that file. Response bodies stay untyped objects. `GET /api/decisions` documents `limit` (default 200) from `app/api.py`, which this slice did not edit.

## S9a Vite and Vue shell

- **Slice id:** S9a
- **Files changed:** `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.js`, `frontend/.gitignore`, `frontend/index.html`, `frontend/src/main.js`, `frontend/src/App.vue`, `frontend/src/style.css`, `frontend/src/api.js`, `frontend/src/books.js`, `frontend/src/constants.js`, `frontend/src/idleReload.js`, `frontend/src/providers.js`, `frontend/src/shellState.js`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `static/**`, `app/**`, `stager_core/**`, `tests/`
- **Tests run:** `py -3 -m pytest` — 362 passed, 0 skipped, 13 e2e deselected. No product network. The browser pass used a temporary seeds/library/config directory and `STAGER_METADATA_BACKEND=fixture`.
- **Browser pass:** Vite at `http://127.0.0.1:5173/` proxied `/api` to the fixture server. `GET /` on that server still returned `static/index.html` (`static/app.js`, no Vite). Chrome (Playwright, headless) loaded the shell, saw `GET /api/session/status` → `no_scan` and the pre-scan scrim, then provider chips after `GET /api/metadata/providers` and `POST /api/metadata/providers/test` (Audnexus, Audible, and Open Library ok; Google Books and MAM missing-key). Start Scan posted `/api/scan`. Two polls were 1526 ms apart, and each `GET /api/scan/{id}` was followed by `GET /api/books?partitioned=true&status=&q=`. Cancel during discovery returned 200, skipped the finish tail, and toasted “Scan cancelled”. A later completed scan held the scrim on “Finishing scan…” for 1.516 s, then home showed `pending 2 · staging 2`. A faked 16-minute hide showed “You've been away for a while” and Reload, which reloaded into session `fresh`. The four section placeholders and the empty detail, settings, confirm, conflict, and staging-scrim shells were in the page. Opening settings made no `/api/auto/settings` call.
- **Remaining risks:** `auto_running`, a 409 from `POST /api/scan`, and the 3000 ms poll retry were not exercised. Finish-scan animation defaults on; the localStorage off switch was not toggled. Cancel during the last book's metadata can still finish as completed, because the worker writes completed after that book; cancel during discovery did skip the tail. The 15-minute prompt was simulated with `visibilitychange`, not a real 15-minute hide. The Cursor browser tab could not be kept open, so this pass used headless Chrome. The dev server is the only Vue entry; FastAPI still serves the old page. Staging rows, conflict dialogs, and auto-stage settings are still later slices. The book refresh keeps counts only.
- **Not verified:** a live auto-run resume, scan-already-running resume, poll failure retry, the finish tail with the animation preference off, and a real 15-minute tab hide.

## S9b Staging list

- **Slice id:** S9b
- **Files changed:** `frontend/src/App.vue`, `frontend/src/shellState.js`, `frontend/src/style.css`, `frontend/src/staging.js`, `frontend/src/stagingState.js`, `frontend/src/StagingList.vue`, `frontend/src/BookDetail.vue`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `static/**`, `app/**`, `stager_core/**`, `tests/`
- **Tests run:** `py -3 -m pytest` — 362 passed, 0 skipped, 13 e2e deselected. No product network. The browser pass used a temporary seeds/library/config directory and `STAGER_METADATA_BACKEND=fixture`.
- **Browser pass:** Vite at `http://127.0.0.1:5173/` proxied `/api` to the fixture server. The library had 55 generated books. Headless Chrome loaded the shell (`session: no_scan`), showed the next list query `partitioned=true&status=pending&q=&limit=50&offset=0`, then Start Scan. After the scan, page 1 rendered 50 rows (not 55). Search `Book 54` sent `q=Book+54` and showed 1 row. Next page sent `offset=50` and showed 5 rows. Staged and skipped filters sent `status=staged` and `status=skipped`. Sort on the page moved the first author from Author 00 to Author 49 and the header toggle moved it back. Detail typed a new author, `POST .../target-key-preview` updated the library path, Save sent PATCH and the author badge became Manual, field revert and Revert all returned it to Suggested, Re-lookup returned, and Load duration showed `0m`. Skip and unskip returned 200. One row Approve and a two-book bulk approve returned 200. Bulk unstage asked “Unstage 2 books?” and `POST /api/books/bulk-revert` cleared the staged page. Row unstage used the confirm dialog and `POST .../revert`.
- **Remaining risks:** Each scan poll still requests the S9a count URL (`/api/books?partitioned=true&status=&q=`, API default limit 500) and then the paged list. The status line’s staging count follows that count response. The section badge and the rows follow the 50-row page. Next page is enabled when the page is full, so a library whose filtered count is an exact multiple of 50 offers one empty page after the last full page. Pending books that are in a conflict or a merge are not selectable; this fixture had neither. The “Don’t show again” checkbox on unstage was not checked. The mobile bulk bar was not opened at a narrow width.
- **Not verified:** the Cursor browser tab (it would not open), a library with zero books (this fixture had 55; empty staged and skipped filters were shown), conflict or merge rows, the don’t-show-again preference, and the mobile bulk bar.

## S9c Conflicts, merges, partial stage

- **Slice id:** S9c
- **Files changed:** `frontend/src/App.vue`, `frontend/src/shellState.js`, `frontend/src/stagingState.js`, `frontend/src/BookDetail.vue`, `frontend/src/style.css`, `frontend/src/groups.js`, `frontend/src/resolveState.js`, `frontend/src/partialState.js`, `frontend/src/GroupList.vue`, `frontend/src/ConflictDialog.vue`, `frontend/src/PartialList.vue`, `frontend/dist/` (vite production build), `docs/rework/SLICE-LOG.md`
- **Files not changed:** `static/**`, `app/**`, `stager_core/**`, `tests/`
- **Tests run:** `py -3 -m pytest` — 362 passed, 0 skipped, 13 e2e deselected. No product network. The browser pass used a temporary seeds/library/config directory and `STAGER_METADATA_BACKEND=fixture`.
- **Browser pass:** Vite at `http://127.0.0.1:5173/` proxied `/api` to the fixture server. `GET /` on that server still returned `static/index.html` (`static/app.js`, no Vite). Headless Chrome loaded `session: no_scan`, clicked Start Scan, then the conflicts section showed 2 groups (`data-rendered=2` of `data-total=2`): Shared Title and Split Book. Opening Shared Title showed Select and Merge. Merge preview listed `copy-a.mp3` and `copy-b.mp3` via `POST /api/merges/.../preview`. Select posted `POST /api/conflicts/Conflict%20Author/Shared%20Title/approve` and toasted “Winner staged”. The dialog moved to Split Book; Merge & stage posted `POST /api/merges/Merge%20Author/Split%20Book` and the conflicts section became “No conflicts.” Partial showed `1 / 3` plus one extra. Remove extras confirmed and posted `POST .../remove-extras`. Detail showed `01.mp3 linked`, `02.mp3 unlinked`, `03.mp3 unlinked`. Link missing files posted `POST .../complete-partial`, toasted “Book fully staged”, and the partial section became empty. Status ended `pending 0 · staged 3 · skipped 1 · partial 0 · conflicts 0`. No request hit bare `GET /api/conflicts` or `GET /api/merges`.
- **Remaining risks:** Conflict and merge rows are sliced in the client from the capped `GET /api/books` arrays (page size 50). This fixture had 2 groups and 1 partial, so the next-page button was not exercised. Opening a group still calls `GET /api/conflicts/{target_key}` and `GET /api/merges/{target_key}`. The section badge counts the current page. Seed/seed approve skipped the losing copy (the skipped count went to 1).
- **Not verified:** the Cursor browser tab (it would not stay open; this pass used headless Chrome), a library-side replace confirm, Save all edits, Skip this book, a manual Next conflict click, filename-collision edits, the merge-selection confirm, Don’t show again, a second page of 50 groups, and a narrow viewport.

## S9d Auto-stage, away review, retire old page

- **Slice id:** S9d
- **Decision ids:** D01, D04, D07, D09
- **Files changed:** `frontend/src/App.vue`, `frontend/src/shellState.js`, `frontend/src/constants.js`, `frontend/src/style.css`, `frontend/src/StagingList.vue`, `frontend/src/BookDetail.vue`, `frontend/src/resolveState.js`, `frontend/src/sections.js`, `frontend/src/titleExtraction.js`, `frontend/src/awayState.js`, `frontend/src/settingsState.js`, `frontend/src/AwayList.vue`, `frontend/src/SettingsDialog.vue`, `frontend/package.json`, `frontend/vite.config.js`, `frontend/.gitignore`, `frontend/dist/` (vite production build, base `/static/`), `app/main.py` (`/` and the `/static` mount only), `tests/e2e/conftest.py`, `tests/e2e/helpers.py`, `tests/e2e/test_a_smoke.py`, `tests/e2e/test_e_conflicts.py`, `tests/e2e/test_h_lvi.py`, `tests/e2e/test_k_toolbar.py`, `docs/rework/SLICE-LOG.md`. Deleted `static/app.js` and `static/index.html`.
- **Files not changed:** `static/style.css` (still on disk, no longer mounted), `app/services/**`, `app/repositories/**`, `stager_core/**`, product API routes, `Dockerfile`
- **Old page deleted:** yes, after Playwright was green. `static/app.js` and `static/index.html` are gone. `/` returns `frontend/dist/index.html`. `/static` mounts `frontend/dist`. `STATIC_DIR` now points at that build so `tests/test_openapi_pagination.py` still sees an index file without an edit.
- **Tests run:** Before the delete, `py -3 -m pytest` — 362 passed, 13 deselected, and `py -3 -m pytest -m e2e` — 13 passed (Vite UI, `STAGER_METADATA_BACKEND=fixture`). After the delete and the `/` switch: `py -3 -m pytest` — 362 passed, 13 deselected, 25.10s; `py -3 -m pytest -m e2e` — 13 passed, 362 deselected, 83.00s, against FastAPI `/` (no Vite, because `static/index.html` was gone). No real library. No commit.
- **Browser pass:** Headless Playwright Chromium against Vite `http://127.0.0.1:12406/` proxying a temporary fixture API on `12405` (`STAGER_METADATA_BACKEND=fixture`, happy scan: Red Rising, Project Hail Mary, Golden Son). The Cursor IDE tab would not stay open. Home appeared after scan. Settings loaded interval `2`; a later save sent PATCH `interval_hours` 4. Auto polls were 2 with a last gap of 1565 ms. Cancel returned home. After a full auto-run the away list had 2 rows; dismiss one left 1; revert with confirm emptied the list. `stager.sectionCollapsed.awaySection` stayed `"1"` across reload. Cache clear showed the confirm dialog, stored `stager.confirmSkip.clear-metadata-cache`, and the second click skipped the dialog. The built `/` page was then covered by the post-delete Playwright suite, not by a second settings/away click-through.
- **Not verified:** clicking Okay all (`#dismissAllAwayBtn` stayed hidden). After dismiss and revert the leftover books were ineligible at `min_confidence` 0.9 (displayed confidence 0.00 and 0.55), and a fill of 0.5 did not persist on the next settings GET. Also not verified: the Cursor IDE browser tab, a real 15-minute idle hide, a library-side replace, and settings/away clicks on the built bundle itself. `Dockerfile` still copies `static/` and not `frontend/dist`, so an image built from that file would not serve this page. `npm` was not on PATH; the build was `vite build --base /static/` via the Cursor Node binary, which is the `package.json` build script.

## S10 Media-kind seam

- **Slice id:** S10
- **Decision ids:** D06
- **Files changed:** `stager_core/media_kind.py`, `stager_core/discovery.py`, `stager_core/metadata/tags.py`, `tests/test_media_kind.py`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `tests/test_discovery_parts.py` (no import had to move), `stager_core/metadata/providers.py`, `app/`, `frontend/`, `static/`
- **Tests run:** `py -3 -m pytest` — 365 passed, 0 skipped, 13 e2e deselected, 25.03s. No network. `tests/test_media_kind.py` and `tests/test_discovery_parts.py` passed.
- **Remaining risks:** `AUDIO_EXT` is the audiobook kind's suffix set, re-exported from `discovery.py`. `staging.py`, `duration.py`, `target_index.py`, and `conflicts.py` still import that set and do not call `get_kind`, so a later kind stays invisible to those walks. There is no media-kind column, and epub and mobi files in a seed stay undiscovered. `media_kind` cannot import `stager_core.metadata` at module scope: that package imports lookup, which imports discovery, which imports the seam. Mutagen stays inside `read_audiobook_tags`, loaded only after the audiobook kind is selected. There is no plugin loader; a later format is a new `_KINDS` entry, not a parser.

## S11 Docs

- **Slice id:** S11
- **Decision ids:** D03, license GPL-3.0-only
- **Files changed:** `README.md`, `CONTRIBUTING.md`, `docs/rework/SLICE-LOG.md`
- **Files not changed:** `LICENSE`, `docs/pinning-model.md`, `docs/rework/**` other than this log, `app/**`, `stager_core/**`, `static/**`, `frontend/**`, `Dockerfile`, `docker-compose.yml`, `tests/`
- **Tests run:** `py -3 -m pytest` — 365 passed, 0 skipped, 13 e2e deselected, 24.65s. No network. No product code edited.
- **Remaining risks:** The Vue subtitle still says only `Author/Series/Title`. The README states that layout and flat `Author/Title` when series is empty or pinned empty, including the `{index} - Title` folder from `compute_target_key`. `Dockerfile` still copies `static/` (`style.css` only; `static/app.js` and `static/index.html` are gone) and copies `frontend/dist`, which is what `/` serves. A MyAnonaMouse cookie file can still enable that provider when `STAGER_MAM_ID` and `MAM_ID` are blank; the README does not document cookie files. Provider status still resolves MAM without `MAM_ID`, so the chip can show it off when only that fallback is set. This slice did not start Docker or click through a scan.
