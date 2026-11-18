# Backend module boundaries (observed)

Document scope: production backend under `app/` and `stager_core/` as it exists in the repo. Seams are observations only—not a target layout.

Evidence cites `path:line` unless noted. Line counts are the final line number in each file (measured from file reads, 2026-11-17).

---

## `app/` versus `stager_core/`

### Observed behavior

**`app/`** (10 modules) is the FastAPI host and operator-facing orchestration:

| Module | Role (observed) |
|--------|------------------|
| `app/main.py` | FastAPI app, static mount, `startup`/`shutdown` wiring |
| `app/api.py` | HTTP routes (`/api/*`), request models,大部分 business endpoints |
| `app/db.py` | SQLite schema, `connect()`, migrations, CRUD helpers, `DB_LOCK` |
| `app/scan.py` | `ScanManager`, background scan thread, `ScanProgress` |
| `app/auto.py` | `AutoRunManager`, background auto-run thread |
| `app/session.py` | In-memory `StagingSession` (library index, conflicts, hydration) |
| `app/scheduler.py` | APScheduler interval job for scheduled auto-stage |
| `app/activity_lock.py` | SQLite-backed operator activity window |
| `app/settings.py` | Paths to DB and filesystem roots via env |
| `app/fingerprint_cache.py` | SQLite-backed fingerprint cache for scans |

**`stager_core/`** (34 Python modules) holds domain logic with no FastAPI dependency in the package tree, except one deliberate reverse import (see below):

- **Discovery / filesystem:** `discovery.py`, `paths.py`, `fingerprint.py`, `target_index.py`
- **Staging / library FS:** `staging.py`, `library_cache.py`
- **Conflicts / merges:** `conflicts.py`, `merges.py`
- **Auto rules:** `auto_eligibility.py`
- **Metadata subtree:** `metadata/*` (lookup, providers, scoring, LVI, tags, normalization, etc.)

**Import direction (observed):**

- `app/*` imports `stager_core.*` extensively (e.g. `app/api.py:18–61`, `app/db.py:12–22`, `app/scan.py:14–21`, `app/session.py:10–20`).
- No `from app` / `import app` at module top level under `stager_core/` **except** lazy imports inside `stager_core/library_cache.py:17,55,69` (`from app.api import holder`).
- `stager_core/__init__.py:3–4` re-exports only `discover_books`, `FlatBook`, `stage_book_author_title`, `BookResult`—not the full core surface.

**Who calls whom:**

- HTTP → `app/api.py` handlers → `holder` (conn, session, managers) + `app/db` helpers + `stager_core` for FS/metadata/conflicts/staging (`app/api.py:130–138`, routes throughout).
- `app/main.py:44–61` creates `connect()`, assigns `holder`, builds `ScanManager` / `AutoRunManager`, starts scheduler tick calling `try_scheduled_tick` (`app/auto.py:510–514`).
- `ScanManager` uses `MetadataLookupService(conn)` (`app/scan.py:206–207`) and `discover_books` / `build_target_indexes` from core.
- `StagingSession` uses core index builders and `app.db` persistence (`app/session.py:59–76,220–250`).
- Tests and tools import both packages; E2E lives under `tests/e2e/`.

### Inference

- **`app/`** owns process lifecycle, HTTP contract, SQLite access coordination, and long-running scan/auto threads.
- **`stager_core/`** owns pure(ish) algorithms and filesystem operations; persistence of API/provider cache goes through a `sqlite3.Connection` passed in from `app` (`stager_core/metadata/cache.py:13–50`).

### Tests that lock this

- `tests/test_no_research_imports_in_stager.py` — AST scan of `app/` and `stager_core/` for `research` imports.
- Broad integration tests patch `app.api.holder` (e.g. `tests/test_bulk_approve.py`, `tests/test_session_status.py`).
- Core behavior: `tests/test_conflicts.py`, `tests/test_staging_session.py`, `tests/test_discovery_parallel.py`, etc.

### Single-operator assumptions

- One running FastAPI process with one populated `holder` (`app/main.py:38–61`).
- One operator UI; no multi-tenant session isolation in code paths reviewed.

### Unknowns

- Whether production runs multiple Uvicorn workers (not configured in `app/main.py`; would break single-`holder` / single-connection design if `>1` worker without external coordination).

---

## `ScanManagerHolder` (process-wide holder)

### Observed behavior

Defined as a plain dataclass-like object in `app/api.py:130–138`:

```text
manager: ScanManager | None
auto_manager: AutoRunManager | None
conn: sqlite3.Connection | None
session: StagingSession | None
scheduler_tick: Any
```

Module singleton: `holder = ScanManagerHolder()` (`app/api.py:138`).

**Created / wired:**

- `app/main.py:44–59` on FastAPI `startup`: `connect(db_path())` → `holder.conn`; hydrate or fresh `StagingSession` → `holder.session`; `ScanManager` → `holder.manager`; `AutoRunManager` → `holder.auto_manager`; closure `tick` → `holder.scheduler_tick`.

**Cleared:**

- `app/main.py:67–73` on `shutdown`: closes `holder.conn`, nulls all fields.

**Mutated at runtime:**

- `app/api.py:236–245` — `_ensure_session()` may replace `holder.session` if missing or books/library roots differ from `holder.manager`.
- Scan/auto/session/db updated through handler side effects (e.g. `session.apply_stage`, `session.refresh_resolution_groups`) using `holder.conn` / `holder.session` (many sites in `app/api.py`, e.g. `422–423`, `1155–1157`).
- `stager_core/library_cache.py:71–73` — `invalidate_library_cache` sets `holder.session.session_ready = False` and `stale = True` when import succeeds.
- Unit tests assign `holder.*` in `setUp`/`tearDown` (e.g. `tests/test_health.py:25–36`).

**Read by:**

- Essentially all `/api` endpoints via `holder` (`app/api.py`).
- `stager_core/library_cache.py` for warm inode/library indexes when `session.session_ready` (`stager_core/library_cache.py:15–22`).

### Inference

- The holder is the de facto **service locator** for the single process; it is not thread-safe as a structure, but collaborators use `DB_LOCK` and per-component locks for SQLite and progress.

### Tests that lock this

- `tests/test_health.py` — health checks with `holder` populated.
- `tests/test_scan_cancel.py` — cancel via `holder.manager`.
- `tests/test_session_status.py` — `get_session_status()` with `holder.session`.

### Single-operator assumptions

- Exactly one `holder` per process; tests reset global state manually.

### Unknowns

- None material for holder fields; scheduler stores only the tick callable, not the APScheduler instance (`app/main.py:59`, `app/scheduler.py:11–12` module global `_scheduler`).

---

## SQLite connection ownership

### Observed behavior

**Definition:** `app/db.py:496–507` — `connect(db_file: Path)`:

- `sqlite3.connect(..., check_same_thread=False)` (`app/db.py:498`)
- `PRAGMA journal_mode=WAL` (`app/db.py:500`)
- `PRAGMA busy_timeout=10000` (`app/db.py:501`)
- `executescript(SCHEMA)`, `_migrate_schema(conn)`, `ensure_auto_defaults`, `ensure_session_meta_defaults`, `commit`

**`DB_LOCK`:** `threading.RLock()` at `app/db.py:24`; used across `app/api.py`, `app/scan.py`, `app/auto.py`, `app/session.py`, `app/fingerprint_cache.py`, and some helpers in `app/db.py` (e.g. `953+`).

**Connection count (production path):**

- One long-lived connection stored in `holder.conn` (`app/main.py:44–45`), closed on shutdown (`app/main.py:67–68`).
- `db_conn()` context manager (`app/db.py:510–516`) opens and closes per use—**no production callers found** in `app/`; tests use `connect()` directly.

**Other connections:**

- `tools/diagnose_lvi.py:140` — read-only URI connection to an existing DB (diagnostic tool, not app runtime).
- Tests: each test file typically `connect(tmp_path / "test.db")` and `close()` in `tearDown`.

**Not all DB writes take `DB_LOCK`:** e.g. `app/activity_lock.py:20–28` — `renew_activity_lock` executes `UPDATE` and `commit()` without acquiring `DB_LOCK` (callers often hold `DB_LOCK` in `app/api.py:512–513` via `_renew_lock`).

**`MetadataLookupService` / `ApiCache`:** share the same `conn` passed from `ScanManager` (`app/scan.py:206–207`); cache reads/writes hit `api_cache` table (`stager_core/metadata/cache.py:23–50`).

### Inference

- Design intent is **one WAL-mode SQLite file, one shared connection, explicit `DB_LOCK` serialization** for most mutating paths; `check_same_thread=False` allows scan/auto threads and FastAPI worker thread to share the connection.

### Tests that lock this

- `tests/test_health.py` — optional check that health degrades if `DB_LOCK` not acquired within timeout (`app/api.py:557–563`, test asserts message).
- `tests/test_fingerprint.py` — second `connect()` to same file for persistence round-trip.
- `tests/test_chosen_pin_migrate.py` — multiple `connect()` calls exercise migration idempotency.

### Single-operator assumptions

- Single DB file at `settings.db_path()` (`app/settings.py:13–16`, env via `STAGING_CONFIG_ROOT` / `STAGER_CONFIG_ROOT` in `stager_core/paths.py:21–25`).
- No connection pooling layer.

### Unknowns

- Complete inventory of code paths that `commit()` without `DB_LOCK` (partial review; `activity_lock` confirmed).

---

## Process model: threads, scheduler, activity lock

### Observed behavior

| Mechanism | Location | Behavior |
|-----------|----------|----------|
| Scan thread | `app/scan.py:298–304` | Daemon `threading.Thread` runs `_run_scan`; at most one alive thread guarded by `ScanAlreadyRunning` (`app/scan.py:279–282`) |
| Auto thread | `app/auto.py:137–143` | Daemon thread runs `_run_auto`; `AutoRunAlreadyRunning` if already running (`app/auto.py:105–107`) |
| APScheduler | `app/scheduler.py:15–28` | `BackgroundScheduler`, job id `audiobook_auto_stage`, `max_instances=1`, `coalesce=True`, interval from `auto_settings.interval_hours` (min 0.25h) |
| Scheduled tick | `app/main.py:55–57`, `app/auto.py:510–514` | Calls `auto_manager.start_run(trigger="scheduled")`; swallows `AutoRunAlreadyRunning` / `AutoRunBlocked` |
| Activity lock | `app/activity_lock.py:13–51` | Row `activity_lock.id = 'default'`; `locked_until` vs UTC now; duration from `lock_timeout_minutes` in `auto_settings` |
| Conflict compute lock | `app/api.py:91,282,292` | `_compute_conflicts_lock` serializes `refresh_resolution_groups` for conflict/merge API paths |
| Scan progress lock | `app/scan.py:74,153` | `ScanProgress` uses inner lock + `DB_LOCK` on flush (`app/scan.py:153–185`) |
| Pool workers | `app/scan.py:349`, `app/api.py:1825,2637`, `stager_core/discovery.py:221` | `ThreadPoolExecutor` for parallel FS/metadata work (not separate DB connections) |

**One-at-a-time rules (observed):**

1. **Manual scan vs auto-run:** `app/api.py:789–798` — `POST /scan` returns 409 if `auto_manager.is_running()`; `app/api.py:799–806` — `ScanAlreadyRunning` if scan thread alive.
2. **Auto vs scan:** `app/auto.py:113–115` — `start_run` raises `AutoRunBlocked` if manual scan thread alive; `app/auto.py:90–93` — scheduled path also checks scan.
3. **Scheduled auto vs activity lock:** `app/auto.py:94–95,117–120` — `can_start_scheduled` / `start_run(trigger="scheduled")` block when `is_activity_lock_active`; manual trigger may pass `bypass_activity_lock=True` (`app/auto.py:103,121–122`, `app/api.py:2431+`).
4. **Auto-run may start scan:** `app/auto.py` (~298) calls `scan_manager.start_scan(auto_run_id=run_id)` inside auto workflow (nested scan, still one scan thread).
5. **Stale reconciliation:** On manager init, DB rows with `status='running'` for scans/auto_runs are marked failed if no live thread (`app/scan.py:217–231`, `app/auto.py:57–72`).

**Activity lock renewal:** Operator mutations call `_renew_lock(reason)` in `app/api.py:509–513` from many endpoints (scan start, approve, patch, bulk ops, etc.).

### Inference

- **Operator activity** suppresses **scheduled** auto-stage; **manual** scan and **manual** auto-run have explicit bypass paths for activity lock.
- Parallelism is FS/CPU-bound (executors), not multiple SQLite writers without `DB_LOCK`.

### Tests that lock this

- `tests/test_activity_lock.py`
- `tests/test_auto_manual_run.py`
- `tests/test_scan_cancel.py`
- `tests/test_auto_change_feedback.py` (activity lock + holder)

### Single-operator assumptions

- One machine, one stager process, one operator session implied by global activity lock row `default` (`app/db.py:737–741`).

### Unknowns

- Exact auto-run phase diagram end-to-end without reading full `app/auto.py:265–500` (high-level thread + `start_scan` coupling confirmed).

---

## Large modules (line counts)

Measured as **last line number in file**:

| Lines | Path |
|------:|------|
| 2811 | `app/api.py` |
| 1451 | `app/db.py` |
| 986 | `app/scan.py` |
| 515 | `app/auto.py` |
| 289 | `app/session.py` |
| 931 | `stager_core/staging.py` |
| 919 | `stager_core/metadata/providers.py` |
| 421 | `stager_core/metadata/lookup.py` |
| 542 | `stager_core/metadata/title_cleanup.py` |
| 491 | `stager_core/metadata/lvi.py` |
| 400 | `stager_core/conflicts.py` |
| 337 | `stager_core/discovery.py` |

Other `stager_core/metadata/` files in the 250–350 line range include `scoring.py`, `library_vocab.py`, `series_scoring.py`, `cleanup_pipeline.py`, `normalize.py` (per repo search tree; exact counts not repeated here unless needed for rework prioritization).

**`app/api.py`** concentration: FastAPI routes, bulk approve/revert thread pools, conflict/merge approve, health, auto settings, decision logs, book CRUD—holder-centric (`app/api.py:90+`).

**`app/db.py`:** schema string (`app/db.py:49–297`), `_migrate_schema` (`app/db.py:300–441`), book/scan/auto CRUD, session meta, library_targets, decision logs.

---

## `provider_registry.py` versus `providers.py`

### Observed behavior

**`stager_core/metadata/provider_registry.py` (76 lines):**

- `PROVIDER_DEFS` — static list of provider ids/labels/env key requirements (`provider_registry.py:6–12`).
- `list_provider_status()` — enabled/configured flags from env (`provider_registry.py:29–45`); uses `resolve_stager_mam_id()` from providers for MAM (`provider_registry.py:22–25`).
- `probe_provider()` / `test_all_providers()` — delegate to `MetadataProviders.probe_connectivity` (`provider_registry.py:48–75`).

**Still in `stager_core/metadata/providers.py` (919 lines):**

- Env / `.env` loading (`providers.py:35–66`, `_RESEARCH_ENV_KEYS` at `providers.py:27–31` — names only, not values).
- MAM cookie path, persistence, ID resolution (`providers.py:72–132`).
- `mam_search_body`, scoring helpers, **`MetadataProviders` class** — HTTP clients, per-provider search, caching via `ApiCache`, probe implementation (`providers.py:217+`, `probe_connectivity` at `providers.py:850+`).
- Duplicate probe constants `_PROBE_*` at file bottom (`providers.py:916–918`) and in registry (`provider_registry.py:14–16`).

**Consumers:**

- `MetadataLookupService` imports registry for `list_provider_status` / `test_all_providers` and providers for `MetadataProviders` (`stager_core/metadata/lookup.py:29–35`).
- API exposes provider status via `holder.manager.lookup` (`app/api.py:643–652`).

### Inference

- Registry is a **thin catalog + health UI layer**; **all network I/O and candidate construction** remain in `providers.py`.

### Tests that lock this

- `tests/test_provider_registry.py`
- `tests/test_providers_search.py`, `tests/test_fixture_providers.py`
- `tests/test_scan_books_found.py` (imports `list_provider_status`)

### Single-operator assumptions

- Provider credentials via environment / `.env` on the same host as the process.

### Unknowns

- None for split of responsibilities.

---

## `research/` package guard

### Observed behavior

- `tests/test_no_research_imports_in_stager.py:9–12` scans `stager_core/` and `app/` for imports of module `research` or `research.*`.
- **No `research/` directory** present in the workspace tree (glob search 2026-11-17).

### Inference

- Guard is **forward-looking** or for machines where `research/` exists outside this clone.

### Tests that lock this

- `tests/test_no_research_imports_in_stager.py`

### Single-operator assumptions

- N/A

### Unknowns

- Whether `research/` exists only on developer machines not committed (would still fail test if imported).

---

## Session hydration lifetime (`app/session.py`)

### Observed behavior

- Constant `STALE_SCAN_HOURS = 24` (`app/session.py:35`).
- **Startup:** `StagingSession.try_hydrate_from_db(conn, books, library)` (`app/main.py:48–51`). If `None`, new session with `stale = True` (`app/main.py:49–51`).
- **Hydration criteria** (`app/session.py:253–288`):
  - `session_meta.last_scan_finished_at` parseable and age ≤ 24h (`app/session.py:261–272`)
  - `count_books(conn) > 0` (`app/session.py:273–274`)
  - `load_library_targets(conn)` non-empty (`app/session.py:275–277`)
  - Rebuilds `inode_index` from library index, sets `session_ready = True`, `stale = False`, calls `refresh_resolution_groups` and `rebuild_lvi` (`app/session.py:279–287`).
- **Persistence:** `persist_scan_snapshot` writes `library_targets` + `session_meta` (`app/session.py:220–238`); per-target updates via `persist_library_target` (`app/session.py:240–250`).
- **Lifetime:** In-process for server uptime; replaced only if `_ensure_session` recreates it or shutdown clears holder. Hydration does not re-run automatically after startup except via new `StagingSession` + scan snapshot flow.
- **API gating:** `_require_session_ready` HTTP 409 if not `session_ready` or `stale` (`app/api.py:265–272`); `get_session_status` exposes `session_hydrated` (`tests/test_session_status.py`).

### Inference

- Hydration is a **fast restart optimization** within 24h of last completed scan, not a durable multi-process cache.

### Tests that lock this

- `tests/test_session_persistence.py`
- `tests/test_session_status.py`
- `tests/test_staging_session.py`

### Single-operator assumptions

- Clock on server is authoritative for 24h window.

### Unknowns

- Whether operators rely on hydration after partial scan failure (depends on `last_scan_finished_at` and library_targets population).

---

## Ad-hoc migrations: `PRAGMA table_info`, `schema_flags`

### Observed behavior

- On every `connect()`, after `SCHEMA` script: `_migrate_schema(conn)` (`app/db.py:503`) uses **`PRAGMA table_info(...)`** on `auto_actions`, `scans`, `books`, `auto_settings` to conditionally `ALTER TABLE ADD COLUMN` (`app/db.py:301–441`).
- One-time data repair: `_repair_false_chosen_pins` (`app/db.py:469–493`) gated by **`schema_flags`** key `repair_false_chosen_pins_v1` (`app/db.py:477–478`, `493`).
- **`schema_flags` table** created in `_ensure_schema_flags` (`app/db.py:444–451`); helpers `_schema_flag_applied` / `_set_schema_flag` (`app/db.py:455–466`).
- No separate migration runner or version table beyond `schema_flags` keys observed.

### Inference

- Schema evolution is **inline, idempotent ALTERs** plus **flagged one-shot data fixes**.

### Tests that lock this

- `tests/test_chosen_pin_migrate.py` — deletes `schema_flags` to re-run repair (`tests/test_chosen_pin_migrate.py:87–88,108–109`).

### Single-operator assumptions

- Same DB file receives repeated `connect()` calls across restarts on one deployment.

### Unknowns

- Full list of historical columns not in fresh `SCHEMA` but required on old DBs (only migrator body at `app/db.py:300–441` reviewed).

---

## Cross-cutting seam: `stager_core.library_cache` ↔ `app.api.holder`

### Observed behavior

- `get_library_indexes` / `get_inode_index_copy` prefer `holder.session` when `session_ready` and paths match (`stager_core/library_cache.py:15–22,53–60`).
- Otherwise builds indexes from disk and caches in module-level `_cache` (`stager_core/library_cache.py:33–50`).
- `invalidate_library_cache` marks session stale via `holder` (`stager_core/library_cache.py:67–73`).

### Inference

- Only production **core → app** dependency; enables CLI/tools to use core without app when `ImportError`/`holder` absent (`stager_core/library_cache.py:23–24,61–62`).

### Tests that lock this

- `tests/test_library_cache.py`

### Single-operator assumptions

- Library path stable for lifetime of hydrated session.

### Unknowns

- All call sites of `invalidate_library_cache` (not fully enumerated here).