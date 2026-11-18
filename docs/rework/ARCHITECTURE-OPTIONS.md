# Architecture options

Four ways to rework the process mapped in `SYSTEM-MAP.md`. Scale numbers come from `08-scale.md`. Feature status comes from `FEATURE-INVENTORY.md`. This file does not choose. D01 on `OWNER-DECISIONS.md` does.

Operator workflows that exist today (scan, lookup, the scoring and cleanup piles, pinning, approve, skip, revert, conflicts, merges, partial stage, auto-stage, hardlink layout) are in the inventory as core. An option below does not drop one of them. “What breaks” means which current contract or deployment story the option gives up.

## Invariants the code enforces

These are behaviors `04-persistence-filesystem.md` and `02-backend-boundaries.md` show in code. Any option keeps them, because they are the domain rules the tests already lock. A framework change does not create them.

| Invariant | Where the code enforces it |
| --- | --- |
| Book identity is the fingerprint id | `FlatBook.id` from sorted file fingerprints (`04`, `stager_core/discovery.py:306-310`). Cache hit requires path, size, mtime, and algo (`app/fingerprint_cache.py:56-66`) |
| Staged-or-not on scan is inode membership | `book_already_staged` drives `staged` / `partial_staged` (`04`, `app/scan.py:526-538`). If the row says staged and the links are gone, scan sets `pending` and clears `staged_path` (`app/scan.py:559-572`). Upsert can also keep an existing `skipped` or `staged` on conflict (`app/scan.py:705-708`); the destage guard is the path that clears a missing link |
| Unstage unlinks only the same inode | `unstage_book` (`04`, `stager_core/staging.py:735-740`). A different inode is `inode_mismatch` and stays. Library replace (F41) is a different function: it unlinks audio under a resolved directory and does not use this inode test |
| Full stage refuses a partial | `stage_book_author_title` returns without linking when analysis says `partial_staged` (`04`, `stager_core/staging.py:390-394`). Complete-partial is a separate call |
| A different inode at the destination name is not overwritten | `name_collision` (`04`, `stager_core/staging.py:424-437`) |
| Conflicts and merges are different groups | `detect_conflict_groups` includes a library side when the target has files and the source inodes are not all linked (`04`, `stager_core/conflicts.py:218-243`). `detect_merge_groups` skips `has_library_conflict` (`stager_core/merges.py:41-52`) |
| Pin layers on read | Effective value is pinned chosen when `chosen_*_set` is set, otherwise suggested (`01`, `stager_core/metadata/effective.py:73-98`). Rescan keeps `chosen_*` when the flag is set (`03`, `app/scan.py:715-729`). Normal approve and auto-stage write `chosen_*` and leave the flags unchanged (`01`, `app/api.py:1851-1854`, `app/auto.py:412-416`). Conflict save-edits, and conflict or merge approve with overrides, set all four flags (F37). That write split is a scar, not a second definition of effective metadata |
| One scan thread and one auto-run | `ScanAlreadyRunning`, scan 409 while auto is running, `AutoRunBlocked` while a scan is alive (`02`, `app/api.py:789-806`, `app/auto.py:113-115`). The auto-run starts that scan thread inside its own workflow. Scheduler `max_instances=1` |

The same-mount rule is an operator precondition in `README.md:28`. Health does not check it (`04`, `app/api.py:545-628`). It is not an invariant the process enforces. `os.link` still requires it for the link to succeed.

## What scale forces on the choice

`08-scale.md`, observed unless marked inference:

- `GET /api/books` as the UI calls it is **O(library)** SQLite three times (list plus conflict refresh plus merge refresh) plus **O(library)** Python. There is no server `WHERE` for status or `q`.
- Partitioned payload: `staging` is sliced, default 500. `partial`, `conflicts`, and `merges` are returned whole. The page sends no `limit` or `offset` (`05-ui-workflows.md`, `static/app.js:4788-4795`).
- **Inference in `08`:** at 50,000 book rows, one `list_books` touches on the order of 150,000 row-equivalents, and the scan poll does that about every 1.5 seconds while a scan runs.
- Library index build is **O(audio files under the library tree)**. The memory section uses on the order of 500,000 audio files as the planning size. Figures there are marked inference.
- Metadata lookup is one book at a time on one lock, with provider spacing (Audnexus 500 ms default, Open Library and Audible and Google Books about 1000 ms, MAM 120 requests per 60 seconds). **Inference in `08`:** a scan of 50,000 new pending books is dominated by that sequence.
- No test locks `limit=500` or a cap on conflicts or partials (`08-scale.md`, `06-test-inventory.md`).

A 50,000-book library with a paged UI is a bar these costs miss. D07 asks the owner to adopt that bar.

## A. Structural cleanup only

Split the large modules (`app/api.py` 2811 lines, `app/db.py` 1451, `static/app.js` 5951, `providers.py` 919; sizes in `02` and `05`). Keep the vanilla page. Keep the full-table reads.

**What stays.** FastAPI, the current HTTP routes, SQLite, the holder, the domain modules, the invariants above, and the single page. F39 (registry versus `providers.py`) and F45 (`library_cache` importing the holder) can be cleaned up inside this option without a new UI or a new database engine. Behavior of scoring, cleanup, LVI, and oeuvre stays (F03).

**What breaks.** The 50,000-book / paged-UI bar. `08-scale.md` ties the cost to `SELECT * FROM books` and to a client that renders every partial, conflict, and merge. Moving functions between files does not change that. The silent 500-row staging slice stays, with no “load more” (`05` inference, `app/api.py:876-907`). This is the shortest path, and it leaves F38 in place.

## B. Recommended

Same Python domain and FastAPI. SQLite repositories that actually page. A Vue app after the HTTP contract is frozen. The current page stays until the parity list in `05-ui-workflows.md` is green.

**What stays.** `stager_core` behavior and the invariants. FastAPI as the HTTP host (see D). One SQLite file and one writer process (see C), which matches the single Compose service (F35, `07-oss-readiness.md`). The static page keeps serving until parity: four sections, bootstrap from `GET /api/session/status`, 1500 ms scan poll, approve / skip / unstage, conflict and merge dialogs, partial actions, away review, settings. Route compatibility until that list is green is D09. Heuristic piles stay (F03). Credential policy stays as signed D02.

**What breaks.** The list contract the page uses today. `GET /api/books?partitioned=true` currently returns every partial row and every conflict and merge group, and a 500-row staging window the client does not know about (F38, `08-scale.md`). Real pagination means those arrays are pages, and conflict refresh can no longer be three full-table reads on every poll. Clients that assume one response is the whole library have to follow the new query. The vanilla page is retired after parity, not before. `08` does not claim SQLite itself cannot hold 50,000 book rows; it claims the current read pattern and the current page cannot present them.

## C. Replace SQLite

**Only if the product needs more than one writer process.** That requirement rejects the single-folder Docker story: one Compose service, one database file under the config root, one `holder.conn` (`07-oss-readiness.md` `docker-compose.yml`; `04-persistence-filesystem.md` one SQLite database per deployment; `02-backend-boundaries.md` one connection, WAL, `DB_LOCK`).

**What stays if SQLite stays.** The schema, `connect()`, the test suite that opens `connect(tmp_path / "test.db")` (`06-test-inventory.md`), fingerprint rows, and `DB_LOCK` as the writer queue. `08-scale.md` classifies the hot cost as full-table reads and sequential metadata, not as SQLite failing at 50,000 rows. Paging (option B) addresses the measured cost. F46 (activity lock committing without `DB_LOCK`) is a locking scar on this connection, not a reason to change engines.

**What breaks if SQLite is replaced.** One-file backups, the migration style (`PRAGMA table_info` plus `schema_flags`, F29), and every unit test that talks to `sqlite3` through `app/db.py`. Multiple writers also fight the in-memory session: indexes are process-local (`01-product-contract.md`). D08 recommends one operator and no auth, which does not require a second writer.

## D. Replace FastAPI

**Reject.** The tests and the UI speak this HTTP API. A new framework does not fix the transaction script.

**What stays.** Routes under `/api` as `05-ui-workflows.md` lists them, the handlers in `app/api.py`, and the e2e server `uvicorn app.main:app` (`06-test-inventory.md`, `tests/e2e/conftest.py`). `06` counts 54 unit modules and 7 e2e modules that drive those handlers or the core they call.

**What a replacement would break.** The static client’s `fetch` paths (`05` route tables) and the tests that patch `app.api.holder` (`02-backend-boundaries.md`). Parity would be a rewrite of the contract rather than a freeze of it (D09).

**What it would not fix.** Approve, conflict approve, merge, bulk, and scan orchestration live in `app/api.py` (`02-backend-boundaries.md`, 2811 lines). Moving those functions onto another framework leaves the same script: pin-flag writes (F37), the flat replace call (F41), and the three full-table reads (F38).

## How the options relate

| | A cleanup | B recommended | C new database | D new framework |
| --- | --- | --- | --- | --- |
| Meets a 50,000-book paged UI | No (`08`) | Yes, if list and conflict reads become pages | Only if the new engine is also paged; the engine swap is not the measured fix | No, by itself |
| Keeps FastAPI and this `/api` | Yes | Yes | Yes, unless paired with D | No |
| Keeps one SQLite file and one Compose service | Yes | Yes | No | Yes |
| Keeps the current page | Yes | Until the `05` parity list is green | Yes | The page would be rebound to a new API |
| Domain invariants above | Yes | Yes | Yes, if reimplemented | Yes, if reimplemented |
