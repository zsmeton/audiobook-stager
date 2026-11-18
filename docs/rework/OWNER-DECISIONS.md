# Owner decisions

Cards the coordinator asks. Recommended choice, why, what today’s tests lock, and what stays broken if the recommendation is rejected.

Signed: D01 (B), D02, D03 (keep), D04 (keep), D05 (fix), D06 (audiobook-only plus a light media-kind seam, no ebook parser), D07 (yes), D08 (yes), D09 (yes), all 2026-11-17. See `DECISIONS-LOG.md`. No unsigned cards. No further cards: every scar in `FEATURE-INVENTORY.md` has a status. Directions for those scars are noted at the bottom, not opened as questions.

---

## D01 Architecture

**Signed 2026-11-17: B.**

- **Question:** Which architecture option, A, B, C, or D?
- **Recommended:** **B.** Same Python domain and FastAPI. SQLite repositories with real pagination. Vue after the API contract is frozen. The current page stays until the parity list in `05-ui-workflows.md` is green.
- **Why:** `08-scale.md` shows `GET /api/books` reading the full `books` table three times, with `partial`, `conflicts`, and `merges` unbounded, while the page never sends `limit` or `offset`. The report’s inference at 50,000 books is on the order of 150,000 row-equivalents per list, repeated every 1.5 seconds during a scan. Option A splits god files and leaves that read pattern (`ARCHITECTURE-OPTIONS.md`). Option C is for multiple writer processes, which drops the one-service Compose layout (`07-oss-readiness.md`, `02-backend-boundaries.md`). Option D replaces an HTTP API the UI and the tests already call, and leaves the handlers in `app/api.py` to be rewritten anyway (`02-backend-boundaries.md`).
- **Tests that lock today:** The suite speaks FastAPI and SQLite. 54 unit modules and 7 e2e modules (`06-test-inventory.md`). E2E boots `uvicorn app.main:app` (`tests/e2e/conftest.py`). Unit tests call `connect()` on a SQLite file. No test locks pagination of `/api/books` (`06` gap, `08-scale.md`).
- **If the owner rejects B:** **A** ships a split of the large files and misses the 50,000-book paged-UI bar; F38 stays. **C** abandons one database file, one connection, and the single Compose service. **D** breaks the `/api` contract the page and the tests use, and the approve / conflict / scan script remains to be fixed on the new framework.

## D02 Credentialed providers

**Signed 2026-11-17, before this rework. Not an open question.**

Every provider that needs an API key or credential is optional and skipped when unset. Keyless providers stay on. Google Books and MyAnonaMouse stay in the public tree. `METADATA_CONTACT_EMAIL` is an optional contact identity for Open Library, not a credential, and a blank email does not turn that provider off. No public instructions for obtaining a tracker session.

- **Evidence:** Google Books search returns no candidates when the key is empty (`03-metadata-pipeline.md`, `stager_core/metadata/providers.py:718-720`). MAM search returns no candidates when `mam_id` is empty (`providers.py:490-492`). The registry marks both disabled when unset and leaves Audnexus, Audible, and Open Library enabled (`07-oss-readiness.md`, `provider_registry.py:7-11`, `29-45`). Open Library requests are not gated on the contact email (`03-metadata-pipeline.md`, `lookup.py:82-88`, `providers.py:652-685`). When `METADATA_CONTACT_EMAIL` is unset, the User-Agent contact token is the literal `local-dev` (`07-oss-readiness.md`, `lookup.py:82-83`). `07` infers a blank value takes that same fallback. Logged as the single line in `DECISIONS-LOG.md`.
- **Tests that lock today:** `tests/test_provider_registry.py` (key-gated providers marked, probe skips unconfigured Google, keyless providers stay enabled), `tests/test_providers_search.py`, `tests/test_scan_books_found.py:30-44`.
- **This card is not open for rejection in this rework.** Reopening it would contradict the signature: removing Google Books or MyAnonaMouse from the tree, or turning off Audnexus, Audible, or Open Library because a key is unset.

## D03 Library layout

**Signed 2026-11-17: keep.**

- **Question:** Does the library stay `Author/Series/Title`, with flat `Author/Title` when series is empty or pinned empty?
- **Recommended:** **Keep.**
- **Why:** `compute_target_key` builds both shapes (`04-persistence-filesystem.md`, `stager_core/staging.py:300-332`). Pinned empty series is `confirmed_none` and the preview omits the series directory (`stager_core/metadata/effective.py:152-153`, `docs/pinning-model.md:18`). The disk index reads 3-part paths as flat and longer paths as series (`stager_core/target_index.py:30-37`).
- **Tests that lock today:** `tests/test_series_staging.py` (two-level without series, three-level with index), `tests/test_series_patch.py` (empty series confirms none, target-key preview), `tests/test_approve_series_metadata.py`.
- **If the owner rejects the recommendation:** `tests/test_series_staging.py`, `tests/test_series_patch.py`, and `tests/test_approve_series_metadata.py` lock the two-layout behavior. `confirmed_none` would no longer select a distinct flat folder (`stager_core/metadata/effective.py:152-153`). F36 would remain three different public sentences until the README, the HTML subtitle, and the code say the same layout.

## D04 Auto-stage

**Signed 2026-11-17: keep.**

- **Question:** Does auto-stage stay (timer, Run now, eligibility, away queue)?
- **Recommended:** **Keep.**
- **Why:** The running product scans, then hardlinks pending books that are not pinned, not in conflict, and above `min_confidence` (`01-product-contract.md`, `stager_core/auto_eligibility.py:18-37`, `app/auto.py:292-327`). The away list is the operator’s review of that work (`GET /api/auto/review`). The activity lock exists so the timer waits while the operator is active (F18).
- **Tests that lock today:** `tests/test_auto_eligibility.py`, `tests/test_auto_manual_run.py` (manual bypasses the lock, scheduled run does not), `tests/test_manual_approve_review.py`, `tests/test_auto_change_feedback.py`. No Playwright coverage of the settings dialog (`05-ui-workflows.md`).
- **If the owner rejects the recommendation:** Eligibility, the scheduler, the away queue, and the reason for the activity lock stop being product behavior. The tests above lock rules the product would no longer have. Approve, skip, and revert stay (F05–F07). They do not depend on the timer.

## D05 Pinning

**Signed 2026-11-17: fix the inconsistency.**

- **Question:** Does pinning stay as `docs/pinning-model.md`, including a fix so conflict and merge approve do not set all pin flags?
- **Recommended:** **Keep the model, and fix that inconsistency.**
- **Why:** The read model is enforced: effective metadata is the pinned chosen value, otherwise the suggestion (`01-product-contract.md`, `stager_core/metadata/effective.py:73-98`). Normal approve copies effective values into `chosen_*` and does not set `chosen_*_set` (`app/api.py:1851-1854`), which matches `docs/pinning-model.md:22-24`. Conflict save-edits always sets all four flags (`app/api.py:996-997`). Conflict approve and merge approve set all four when the body has overrides (`app/api.py:1074-1082`, `1426-1433`). `03-metadata-pipeline.md` records the same table. Any set flag makes auto-stage skip the book (`stager_core/auto_eligibility.py:27-32`).
- **Tests that lock today:** `tests/test_effective_metadata.py`, `tests/test_manual_suggested_ux.py` (save marks manual, revert clears flags), `tests/test_chosen_pin_migrate.py` (a staging snapshot is not a pin), `tests/test_auto_eligibility.py` (a pin blocks auto-stage), `tests/test_series_patch.py`. They do **not** lock the flag difference between normal approve and conflict or merge approve (`06-test-inventory.md` gap; `01-product-contract.md` gap). `tests/test_conflict_approve.py` locks override staging and save-edits without asserting `_set`.
- **If the owner rejects the recommendation:** The contradictory writes stay (F37). A conflict save or an override approve leaves every field pinned, so later lookup will not refresh those suggestions and auto-stage will skip the book. Rejecting the model itself, rather than only the fix, drops the Manual versus Suggested badges and the `confirmed_none` flat folder (D03).

## D06 Audiobook-only, with a media-kind seam

**Signed 2026-11-17: audiobook-only, with a light media-kind seam so a later format is not locked out. No epub or mobi parser.**

- **Question:** Should the rework stay audiobook-only and add a media-kind seam, with no epub parser and no mobi parser?
- **Recommended:** **Yes.**
- **This is a target, not current behavior.** The eight reports describe an audio pipeline: mutagen tags (`03-metadata-pipeline.md`, `stager_core/metadata/tags.py`), library indexing filtered by `AUDIO_EXT` (`08-scale.md`, `stager_core/target_index.py`), duration sums (`stager_core/metadata/duration.py`), and hardlinks of those seed files. They do not describe a media-kind field, an epub parser, or a mobi parser. Adding the seam is new structure. The reports do not show that seam in the code today.
- **Why:** D07’s scale bar is counted in books and audio files (`08-scale.md`). The tests and fixtures are audio (`06-test-inventory.md`: e2e layouts write MP3s with mutagen). A parser for another format is outside that evidence.
- **Tests that lock today:** Audio discovery, tags, duration, fingerprint of file bytes, and hardlink stage (`tests/test_discovery_parts.py`, `tests/test_duration.py`, `tests/test_asin.py`, `tests/e2e/fixtures_fs.py`). Nothing in `06-test-inventory.md` locks a media-kind column or an epub or mobi parse.
- **If the owner rejects the recommendation:** Either the code stays audio-shaped with no named seam (the situation the reports describe), or the rework takes on a non-audio parser that no report and no test describes. Rejecting the seam does not remove audiobook staging.

## D07 Scale bar

**Signed 2026-11-17: yes.** Owner confirmed the same day that designing for that size is fine and that the UI may change to support it. The figure is a design bar, not a measured library size.

- **Question:** Is the bar about 50,000 books and on the order of 500,000 audio files, with a paged UI, and with list and conflict reads that are not full-table?
- **Recommended:** **Yes.**
- **Why:** `08-scale.md` is the measurement. List is three full `books` reads plus in-Python filters. Conflict groups carry files and candidates. The library walk is O(audio files). The memory section plans for about 50,000 books and about 500,000 audio files, and marks the byte estimates as inference. The UI renders every returned partial, conflict, and merge (`05-ui-workflows.md`). Metadata stays sequential and rate-limited; `08` infers that 50,000 new lookups are dominated by provider spacing, which this card does not raise.
- **Tests that lock today:** Correctness on small fixtures (`tests/test_conflicts.py`, `tests/test_library_cache.py`, `tests/test_target_index.py`, e2e layouts). `06-test-inventory.md` and `08-scale.md`: no test asserts a page size, a conflict cap, or a 50,000-row bound.
- **If the owner rejects the recommendation:** Option A remains enough for structure. F38 stays a supported contract: one response holds every partial and every conflict group, and the staging slice stays a silent 500. The 50,000-book figures in `08` stop being a requirement.

## D08 One operator, no auth

**Signed 2026-11-17: yes.**

- **Question:** One operator per instance, and no authentication?
- **Recommended:** **Yes.**
- **Why:** The process has one holder, one activity-lock row `default`, no auth middleware, and a page that does not send credentials (`01-product-contract.md`, `app/main.py:22-35`; `05-ui-workflows.md`, `static/app.js:1268-1293`; `02-backend-boundaries.md`). Session indexes are process-local. That is F48, a single-operator assumption. Keeping it matches the one-writer story in option B and is the reason option C is not the default.
- **Tests that lock today:** No auth tests (`06-test-inventory.md`). Tests construct one `holder` and one SQLite file. `tests/test_activity_lock.py` locks a single `default` row. E2E assumes a localhost server.
- **If the owner rejects the recommendation:** The API and the page have no login to extend. A second operator is not isolated: one activity lock, one scan thread, one in-memory session (`01`, `02`). Adding auth or a second writer is new product surface, and it pulls the deployment toward option C’s multiple writers. Until that exists, anyone who can reach the port can stage and unstage.

## D09 HTTP routes until Vue parity

**Signed 2026-11-17: yes.**

- **Question:** Do HTTP routes stay compatible until the Vue parity list in `05-ui-workflows.md` is green, after which unused routes may be deleted in the UI slice?
- **Recommended:** **Yes.**
- **Why:** The current page is the operator. Its calls are listed in `05-ui-workflows.md` (session, scan, books, approve, skip, revert, bulk, conflicts, merges, partial, away, settings, providers). The parity checklist in that report is the behavior a replacement UI has to match. Deleting a route before that list is green removes a call the static page still makes. After parity, a route the new UI does not use can leave in the UI slice. `05` already notes routes the static page never calls: `DELETE /api/merges/{primary}` (F27) and `GET /api/auto/feedback`.
- **Tests that lock today:** E2E drives the page (`tests/e2e/test_a_smoke.py` through `test_k_toolbar.py`). API tests lock approve, bulk, conflict approve, merge, session status, scan cancel, and health (`06-test-inventory.md`). They lock the routes they call. They do not lock a promise that every route survives after the parity list is green.
- **If the owner rejects the recommendation:** Routes can change while `static/app.js` still calls them, so the current page breaks before a Vue client replaces it. Or unused routes stay forever, including ones `05` found with no client caller.

---

## Notes

**License.** Owner selected GPL-3.0-only on 2026-11-17. `LICENSE` is the official GNU GPL version 3 text.

**Scars with a direction, and no extra card.** Each is classified in `FEATURE-INVENTORY.md`.

| Item | Direction already in hand |
| --- | --- |
| F36 README layout wording | Follows D03: the code’s two layouts are the product. The README sentence and the HTML subtitle disagree with each other and with that code |
| F37 Conflict and merge pin flags | D05 recommends the fix |
| F38 Unbounded reads | D07 recommends paging; option B is where that happens |
| F39 Registry versus `providers.py` | Structural split under D01 option A or B. Lookup behavior stays (F02, F03, D02) |
| F40 `research` import guard | The test stays. The package is absent (`02-backend-boundaries.md`) |
| F41 Replace path ignores series | The cited functions take author and title only. Fixing it means the delete uses the same key as `compute_target_key` with series, which is the key conflict approve already computes (`app/api.py:1089-1091`). Tests lock the 2-argument helper, not a series folder |
| F42 MAM status versus lookup resolver | Status and lookup should call the same resolver. D02 still stands: unset means skip, and the provider stays in the tree. This note does not say how to obtain a session |
| F43 `exclude.txt` | Definitions only, no caller, no test, no UI. It is not a live operator workflow in this tree |
| F44 `mam_exact` | Leave the scoring prior in place with the rest of F03. No application emitter was found |
| F45 `library_cache` imports the holder | Boundary cleanup under option A or B. Index reuse stays |
| F46 Activity lock outside `DB_LOCK` | Serialize that write with the other users of `holder.conn`. The lock feature stays with D04 and D08 |
| F47 Personal defaults | `07-oss-readiness.md` classifies them as “must become optional config” for a later OSS pass |
| F48 No authentication | D08 recommends keeping the assumption |

Unknowns that are not cards: Uvicorn worker count, scheduler timezone, production JSON sizes and RSS, inode stability off POSIX, and whether a clean clone’s pytest is green. Reports: `02`, `01`, `08`, `04`, `07` unknowns.
