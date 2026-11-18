# Slice contract

Path B, signed in `DECISIONS-LOG.md`. One writer at a time. A slice starts only after the previous slice's harness is green, and only after this contract lists that slice. A slice may not edit a file outside its allowed list.

Order: S1, S2, S3, S4, S5, S6, S7, S8, S9a, S9b, S9c, S9d, S10, S11.

S4 does not start after S1. S2 and S3 both edit `app/api.py`, so the early-start condition is not met. S5, S6, and S7 stay serial because they share book rows and the session. S9a through S9d stay serial.

## S1 Settings and public config

- **Slice id:** S1
- **Decision ids:** D02, D08, F47
- **Files allowed:** `app/settings.py`, `stager_core/paths.py`, `.env.example`, `docker-compose.yml`, `Dockerfile`, `README.md` only for variables this slice introduces, `tests/test_settings_defaults.py` (new), `docs/rework/SLICE-LOG.md`
- **Files forbidden:** `stager_core/metadata/**` (scoring, provider reads, lookup), `app/api.py`, `static/`, `stager_core/discovery.py`
- **Behavior that stays:** One Compose service. No authentication. Open Library still runs when `METADATA_CONTACT_EMAIL` is blank. Credentialed providers stay in the tree. Rate-limit numbers stay where they are read today.
- **Behavior that changes:** Path and deployment defaults are resolved in `app/settings.py`. `stager_core/paths.py` delegates to that module. Unset `BOOKS_ROOT` is `./data/seeds`. Unset `AUDIOBOOKS_ROOT` is `./data/library`. The `/data/Dropbox/Books` and `/data/Audiobooks` fallbacks are gone. `.env.example` and Compose defaults use `./data/seeds` and `./data/library`. `TZ` defaults to `UTC` in `.env.example` and in the Compose `${TZ:-...}` default. `Dockerfile` sets `TZ` only if this slice introduces one, and then the value is `UTC`. `.env.example` lists every variable read under `app/`, `stager_core/`, and `docker-compose.yml`, including `DATA_ROOT`, `STAGER_CONFIG_HOST`, `AUDIOBOOK_STAGER_PORT`, `TZ`, `BOOKS_ROOT`, `AUDIOBOOKS_ROOT`, `STAGER_CONFIG_ROOT`, `STAGING_CONFIG_ROOT`, `GOOGLE_BOOKS_API_KEY`, `METADATA_CONTACT_EMAIL`, `AUDNEXUS_MIN_INTERVAL_MS`, `OPENLIBRARY_MIN_INTERVAL_MS`, `AUDNEXUS_REGION`, `STAGER_MAM_ID`, `MAM_ID`, `MAM_REQUESTS_PER_MINUTE`, `STAGER_MAM_COOKIE_FILE`, `MAM_COOKIE_FILE`, `CONFIG_ROOT`, `STAGER_METADATA_BACKEND`, `STAGER_METADATA_FIXTURES`, `STAGER_FIXTURE_LOOKUP_DELAY_MS`, and `SCAN_FINGERPRINT_WORKERS`. `GOOGLE_BOOKS_API_KEY`, `STAGER_MAM_ID`, and `MAM_ID` are blank and labeled optional. `METADATA_CONTACT_EMAIL` is blank and the comment says it does not gate Open Library.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The defaults and the example file match the list above, provider modules are untouched, and the harness is green.

`app/settings.py` is the one settings module this slice may fill. Reads that already live in `stager_core/metadata/lookup.py`, `stager_core/metadata/providers.py`, `stager_core/metadata/provider_registry.py`, `stager_core/metadata/fixture_providers.py`, and `stager_core/discovery.py` stay there. Those files belong to S4 and S10.

## S2 SQLite repositories

- **Slice id:** S2
- **Decision ids:** D07, D09
- **Files allowed:** `app/db.py`, `app/repositories/` (new; `app/repositories/books.py` holds the list and conflict-refresh queries), `app/api.py` and `app/session.py` only for those queries, `tests/test_d07_bounded_lists.py`
- **Files forbidden:** `static/`, `stager_core/metadata/**`, `stager_core/**` for a new repository, Vue, scoring weights, `tests/test_pin_flag_writes.py`, `tests/test_d05_pin_flags.py`, `tests/test_fitness_boundaries.py`
- **Behavior that stays:** `connect()` and `schema_flags` still open an old `stager.db`. Response keys the current page reads stay: partitioned `staging`, `partial`, `conflicts`, `merges`, and `stats`. Provider HTTP stays out of this slice.
- **Behavior that changes:** SQL for list, conflict refresh, and merge refresh moves out of `app/db.py` into `app/repositories/books.py`. `GET /api/books` filters and pages in SQL. The list response does not include every row. Conflict and merge list construction does not `SELECT` the whole `books` table twice per request. `connect()` adds an index on `books(source_path)` (the list orders by `source_path` and `08-scale.md` records no such index). Unskip `tests/test_d07_bounded_lists.py` and make it pass, including the generated-row test at 50,000 book rows. Those rows are SQL inserts, not audio files.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The skipped D07 tests pass, an old database still opens, the current page can still read the partitioned payload, and the harness is green.

The repository is not under `stager_core/`. A module there that calls `app.db.connect` would be a new `stager_core` import of `app`. `tests/test_fitness_boundaries.py` allows that only from `stager_core/library_cache.py`, and S2 cannot edit that test.

## S3 Services out of app/api.py

- **Slice id:** S3
- **Decision ids:** D09
- **Files allowed:** `app/api.py`, `app/main.py` only to include routers, `app/routers/health.py`, `app/routers/scan.py`, `app/routers/books.py`, `app/routers/conflicts.py`, `app/routers/merges.py`, `app/routers/auto.py`, `app/services/health.py`, `app/services/scan.py`, `app/services/books.py`, `app/services/conflicts.py`, `app/services/merges.py`, `app/services/auto.py`, tests whose import of a moved callable must change
- **Files forbidden:** SQL rewrites beyond S2, `static/`, Vue, removing `holder`
- **Behavior that stays:** Route URLs and status codes stay. `holder` stays the process-global `ScanManagerHolder` defined in `app/api.py` and assigned from `app/main.py` startup. `app/scan.py` and `app/auto.py` stay the scan and auto engines these services call.
- **Behavior that changes:** Routers exist for health, scan, books, conflicts, merges, and auto. Domain orchestration moves into the service modules above. `save_conflict_edits`, `approve_conflict`, `approve_merge`, and `_perform_merge` live in `app/services/conflicts.py` and `app/services/merges.py`. Tests may be edited only to follow a moved import.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The same URLs and status codes respond, `holder` is still assigned at startup, and the harness is green.

## S4 Providers

- **Slice id:** S4
- **Decision ids:** D02
- **Files allowed:** `stager_core/metadata/providers.py`, `stager_core/metadata/provider_registry.py`, new per-provider modules under `stager_core/metadata/` (not `ratelimit.py`), `stager_core/metadata/lookup.py` only for the skip call, `tests/test_provider_registry.py`, and a new test module under `tests/` for the empty-key characterization
- **Files forbidden:** Scoring weights, `tests/test_fitness_boundaries.py`, HTTP client imports (`requests`, `httpx`, `urllib.request`) outside `stager_core/metadata/providers.py` and `stager_core/metadata/ratelimit.py`, live network in tests, `stager_core/metadata/fixture_providers.py`
- **Behavior that stays:** The registry and the fixture double stay. Keyless providers still run. Blank `METADATA_CONTACT_EMAIL` still does not disable Open Library. Lookup still finishes on the keyless providers when a credential is empty. Rate limits stay.
- **Behavior that changes:** The live provider class is split by provider. In one place, `requires_key` providers are disabled and skipped when their credential is empty. A characterization test shows a later provider cannot be called with an empty key. New provider modules call `RateLimitedClient` and do not import an HTTP client, so `tests/test_fitness_boundaries.py` stays green without an edit.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The empty-key test passes with no network, the fitness test is still green, and the harness is green.

## S5 Metadata modules

- **Slice id:** S5
- **Decision ids:** none (no behavior change)
- **Files allowed:** `stager_core/metadata/__init__.py`, `stager_core/metadata/title_first.py`, `stager_core/metadata/title_extraction.py`, `stager_core/metadata/title_matching.py`, `stager_core/metadata/cleanup_pipeline.py`, `stager_core/metadata/types.py`, `stager_core/metadata/normalize.py`, `stager_core/metadata/author_oeuvre.py`, `stager_core/metadata/query.py`, `stager_core/metadata/effective.py`, `stager_core/metadata/library_vocab.py`, `stager_core/metadata/title_cleanup.py`, `stager_core/metadata/series_scoring.py`, `stager_core/metadata/duration.py`, `stager_core/metadata/scoring.py`, `stager_core/metadata/paths.py`, `stager_core/metadata/cache.py`, `stager_core/metadata/fixture_providers.py`
- **Files forbidden:** `stager_core/metadata/providers.py`, `stager_core/metadata/provider_registry.py`, `stager_core/metadata/lookup.py`, `stager_core/metadata/ratelimit.py`, `stager_core/metadata/tags.py`, any provider module S4 added, scoring `CONFIG` value changes, title-cleanup step changes, LVI threshold changes
- **Behavior that stays:** Weights, cleanup steps, LVI thresholds, and lookup results stay. D02 skip behavior from S4 stays.
- **Behavior that changes:** None. Delete a helper only when it is unreferenced and untested.
- **Harness command:** `py -3 -m pytest`
- **Done when:** No scoring, cleanup, or LVI value changed, and the harness is green.

`tags.py` is excluded because S10 owns tag reading. `lookup.py`, the registry, `providers.py`, and `ratelimit.py` are excluded because S4 owns them. `stager_core/metadata/paths.py` is not `stager_core/paths.py` (S1).

## S6 Staging, conflicts, merges

- **Slice id:** S6
- **Decision ids:** D05, F41
- **Files allowed:** `stager_core/staging.py`, `stager_core/conflicts.py`, `stager_core/merges.py`, `app/services/conflicts.py`, `app/services/merges.py`, `docs/pinning-model.md`, `tests/test_pin_flag_writes.py`, `tests/test_d05_pin_flags.py`
- **Files forbidden:** `stager_core/metadata/**`, `static/`, `app/api.py` (holder and list queries), heuristic retunes
- **Behavior that stays:** Hardlinks stay. Normal approve still copies effective values and leaves `chosen_*_set` at 0 unless the operator already pinned a field. Two-argument `replace_library_target(library, author, title)` still deletes the flat `Author/Title` key, so `tests/test_library_replace.py` and `tests/test_library_root_guard.py` stay green without edits. Conflict grouping and merge grouping stay.
- **Behavior that changes:** Conflict save-edits, conflict approve, and merge approve use the same pin flags as a normal field edit. They may copy effective values into `chosen_*`. They set `chosen_*_set` only for a field the operator pinned, including the empty-series rule in `docs/pinning-model.md`. Update that doc. Update `tests/test_pin_flag_writes.py` to the new writes and unskip `tests/test_d05_pin_flags.py`. `replace_library_target` accepts series and series index and deletes the directory `compute_target_key` already computes for that series.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The D05 tests pass, the old replace tests still pass, and the harness is green.

Approve functions are not edited in `app/api.py`. S3 placed them in the two service modules. `app/api.py` remains the holder and the list path for S2 and S7.

## S7 App state

- **Slice id:** S7
- **Decision ids:** D08, F45, F46
- **Files allowed:** `app/main.py`, `app/api.py` (the `holder` / `ScanManagerHolder` object), `app/routers/*.py` and `app/services/*.py` only to receive that object instead of importing a process global, `app/activity_lock.py`, `stager_core/library_cache.py`, tests that assign or patch `app.api.holder`: `tests/test_pin_flag_writes.py`, `tests/test_d05_pin_flags.py`, `tests/test_d07_bounded_lists.py`, `tests/test_scan_cancel.py`, `tests/test_series_patch.py`, `tests/test_decision_log.py`, `tests/test_health.py`, `tests/test_conflict_approve.py`, `tests/test_manual_approve_review.py`, `tests/test_approve_series_metadata.py`, `tests/test_bulk_approve.py`, `tests/test_fitness_boundaries.py`, `tests/test_auto_change_feedback.py`, `tests/test_manual_suggested_ux.py`, `tests/test_activity_lock_exclusion.py`, `tests/test_session_status.py`, `tests/test_merge_groups.py`, `tests/test_bulk_revert.py`, `docs/rework/SLICE-LOG.md`
- **Files forbidden:** Authentication, a second database, pin-flag assertion changes, D07 assertion changes
- **Behavior that stays:** One scan and one auto-run at a time. The in-memory inode index remains the single-writer cache. No login. One SQLite file.
- **Behavior that changes:** The process-global holder is replaced by an object created at startup and passed into the routers. `stager_core/library_cache.py` stops importing `app`. Its module docstring states that a second process must not write the same library. Activity-lock writes take the same `DB_LOCK` as other users of the shared connection (`renew_activity_lock` in `app/activity_lock.py` commits today without that lock). `tests/test_fitness_boundaries.py` expects the `library_cache` allowlist to be empty. In the pin and list tests, change only the holder wiring.
- **Harness command:** `py -3 -m pytest`
- **Done when:** No `stager_core` module imports `app`, the activity-lock write is under `DB_LOCK`, and the harness is green.

## S8 API contract

- **Slice id:** S8
- **Decision ids:** D09
- **Files allowed:** `app/main.py` for the `FastAPI(...)` metadata, `app/routers/health.py`, `app/routers/scan.py`, `app/routers/books.py`, `app/routers/conflicts.py`, `app/routers/merges.py`, `app/routers/auto.py` for declared query parameters, `docs/rework/API.md` only when the running app generates it, a new test that the OpenAPI schema lists pagination parameters
- **Files forbidden:** Deleting `static/`, Vue, `app/services/**` behavior changes
- **Behavior that stays:** `static/` still serves the current page. Route URLs stay.
- **Behavior that changes:** FastAPI publishes OpenAPI. List endpoints document pagination parameters. This slice does not start the Vue app.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The OpenAPI test sees pagination params on the list operations, the static page still loads, and the harness is green.

## S9a Vite and Vue shell

- **Slice id:** S9a
- **Decision ids:** D01, D07, D09
- **Files allowed:** `frontend/**` (new Vite + Vue app)
- **Files forbidden:** `static/**`, `app/**`, `stager_core/**`, deleting the current page
- **Behavior that stays:** `app/main.py` still serves `static/index.html` at `/`. Scan, session, and provider APIs stay.
- **Behavior that changes:** A Vite + Vue shell can show scan progress, session bootstrap, and provider status. Parity items from `docs/rework/05-ui-workflows.md`: single-page shell (toolbar, four sections, scrims), `GET /api/session/status` branching, pre-scan provider load/test and Start Scan, scan poll at 1500 ms plus book refresh, the 1500 ms finish-scan tail, scan cancel, the 15-minute idle reload prompt, and provider chips.
- **Harness command:** `py -3 -m pytest`
- **Done when:** Those checklist items are exercised in the browser against the Vite app, the static page is still served, the harness is green, and the write-up says what the browser pass could not verify.

`frontend/` is the only tree this slice may add. `app/main.py` stays with S7 and S8 until S9d.

## S9b Staging list

- **Slice id:** S9b
- **Decision ids:** D01, D07, D09
- **Files allowed:** `frontend/**`
- **Files forbidden:** `static/**`, `app/**`, `stager_core/**`
- **Behavior that stays:** The static page stays served. Approve, skip, unskip, and revert URLs stay.
- **Behavior that changes:** The Vue staging list pages and searches. Parity items: `GET /api/books?partitioned=true&status=&q=` for the staging section, pending/staged/skipped filter, server search `q`, sort on the current page, row detail/approve/skip/unskip/unstage, bulk approve/unskip/unstage, detail PATCH, target-key preview, revert fields, lookup, and lazy duration. The list must not render every row.
- **Harness command:** `py -3 -m pytest`
- **Done when:** Those flows are exercised in the browser, the harness is green, and the write-up says what the browser pass could not verify.

## S9c Conflicts, merges, partial stage

- **Slice id:** S9c
- **Decision ids:** D01, D07, D09
- **Files allowed:** `frontend/**`
- **Files forbidden:** `static/**`, `app/**`, `stager_core/**`
- **Behavior that stays:** Conflict and merge URLs stay. The static page stays served.
- **Behavior that changes:** Vue covers the unified conflicts and merges list, the Select and Merge tabs, conflict approve, merge preview and approve, and partial complete-partial / remove-extras. The conflict and merge lists are pages, not the whole library.
- **Harness command:** `py -3 -m pytest`
- **Done when:** Those flows are exercised in the browser, the harness is green, and the write-up says what the browser pass could not verify.

## S9d Auto-stage, away review, retire the old page

- **Slice id:** S9d
- **Decision ids:** D01, D04, D07, D09
- **Files allowed:** `frontend/**`, `static/app.js` (delete), `static/index.html` (delete), `app/main.py` only for the `/` response and the `/static` mount, `tests/e2e/`
- **Files forbidden:** Deleting `static/style.css` or any other `static/` file, product API changes, `docs/rework/**`
- **Behavior that stays:** Auto-stage timer, Run now, eligibility, and the away queue stay. Hardlinks stay.
- **Behavior that changes:** Vue covers auto-stage settings (GET/PATCH, run now, 1500 ms auto poll, cancel, cache clear) and away review (list, dismiss, revert). After the parity checklist in `docs/rework/05-ui-workflows.md` is checked off, delete only `static/app.js` and `static/index.html`, and point `/` at the built Vue app. Playwright covers the same flows as `tests/e2e/test_a_smoke.py`, `tests/e2e/test_b_scan.py`, `tests/e2e/test_c_approve.py`, `tests/e2e/test_e_conflicts.py`, `tests/e2e/test_f_merge.py`, `tests/e2e/test_h_lvi.py`, and `tests/e2e/test_k_toolbar.py`.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The checklist is checked off, those Playwright flows pass against Vue, the two static files are gone, the harness is green, and the write-up says what the browser pass could not verify.

## S10 Media-kind seam

- **Slice id:** S10
- **Decision ids:** D06
- **Files allowed:** `stager_core/discovery.py`, `stager_core/metadata/tags.py`, `stager_core/media_kind.py` (new), `tests/test_discovery_parts.py`, `tests/test_media_kind.py` (new)
- **Files forbidden:** An epub parser, a mobi parser, new ebook dependencies, scoring changes, `stager_core/metadata/providers.py`
- **Behavior that stays:** Audiobook discovery and tag reads stay. Ebook formats are not parsed.
- **Behavior that changes:** Discovery and tag reading call a tiny interface in `stager_core/media_kind.py`. Only the audiobook kind exists. Ebook formats are a comment on that interface, not a parser.
- **Harness command:** `py -3 -m pytest`
- **Done when:** The new seam test passes, discovery tests still pass, and the harness is green.

## S11 Docs

- **Slice id:** S11
- **Decision ids:** D03, license GPL-3.0-only (already in `LICENSE`)
- **Files allowed:** `README.md`, `CONTRIBUTING.md` (new), operator docs under `docs/` except `docs/rework/**` and `docs/pinning-model.md`
- **Files forbidden:** `docs/rework/**`, `docs/pinning-model.md`, `app/**`, `stager_core/**`, `static/**`, product behavior changes
- **Behavior that stays:** Author/Series/Title, and flat Author/Title when series is empty or pinned empty. Hardlinks stay. The license file stays the GNU GPL version 3 text.
- **Behavior that changes:** None in the product. README gains a quickstart, configuration, the same-filesystem hardlink requirement, the Docker bind-mount note, which providers need a key and which run with nothing set, and how to run tests. It states both layouts from D03 and drops a layout sentence that disagrees with `compute_target_key`. CONTRIBUTING says a product change needs a decision id. Sample audio described there is a tiny generated fixture, not a copyrighted book.
- **Harness command:** `py -3 -m pytest`
- **Done when:** README matches the layouts and the provider key rules, CONTRIBUTING names the decision-id rule, and the harness is green.

`docs/pinning-model.md` stays with S6. `docs/rework/` is history, except `docs/rework/API.md` if S8 checked in a generated description.

## Stop rules

- A keep or defer feature outside the slice means stop.
- An unrelated pytest failure means stop and report the first failure.
- Do not commit.
- Do not add an epub or mobi parser, authentication, a second database engine, or a different HTTP framework.
- Do not retune scoring, title cleanup, or LVI.
