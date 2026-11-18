# OSS readiness — gaps for a fresh clone (read-only audit)

Evidence uses `path:line` citations. **Observed** = directly supported by the tree; **Inference** = reasoned conclusion, labeled in the final section.

---

## What a stranger cannot do today

### Install as a distributable Python package

- **Observed:** There is no `pyproject.toml`, `setup.py`, or `setup.cfg` in the repo root (directory listing). Dependencies are a flat `requirements.txt:1-5` only.
- **Observed:** `Dockerfile:1-16` installs via `pip install -r requirements.txt` and sets `PYTHONPATH=/app`; there is no documented `pip install -e .` path.

### Configure with only committed docs

- **Observed:** `README.md:9-13` documents Docker Compose only; it does not document a native `uvicorn` workflow (contrast `tests/e2e/conftest.py:95-110`, which starts uvicorn with explicit env vars).
- **Observed:** `docker-compose.yml:11-22` injects a fixed set of environment variables. `MAM_ID`, `MAM_COOKIE_FILE`, `STAGER_MAM_COOKIE_FILE`, `CONFIG_ROOT`, and `STAGER_METADATA_BACKEND` are **not** passed through Compose (grep on `docker-compose.yml`).
- **Observed:** `.env.example:1-23` documents `DATA_ROOT`, `STAGER_CONFIG_HOST`, path defaults, and a subset of metadata vars; it does not mention `MAM_ID`, cookie file overrides, or the fixture metadata backend (`stager_core/metadata/fixture_providers.py:118-119`).

### Run without preparing host mounts and sample content

- **Observed:** Quickstart is `Copy-Item .env.example .env` then `docker compose up` (`README.md:9-13`).
- **Observed:** Default scan and library paths assume a host layout under `/data` with `Dropbox/Books` and `Audiobooks` (`.env.example:10-11`, `stager_core/paths.py:7-18`, `docker-compose.yml:13-14`).
- **Inference:** A stranger who only creates empty `./data` and `./config` can likely start the container (healthcheck `docker-compose.yml:32-36`), but meaningful scan/stage behavior requires audiobook files on the shared mount and same-filesystem hardlinks (`README.md:28`).

### Scan with “empty” metadata credentials (what works vs what does not)

- **Observed:** With `GOOGLE_BOOKS_API_KEY` and `STAGER_MAM_ID` empty, `list_provider_status()` marks Google Books and MAM as not configured and not enabled (`tests/test_scan_books_found.py:30-44`, `stager_core/metadata/provider_registry.py:29-44`).
- **Observed:** Google Books search returns no candidates when the API key is blank (`stager_core/metadata/providers.py:718-720`). MAM search returns `[]` when `self.mam_id` is empty (`stager_core/metadata/providers.py:490-492`).
- **Observed:** Audnexus, Audible, and Open Library are registered with `requires_key: False` (`stager_core/metadata/provider_registry.py:7-9`) and remain **enabled** in the provider list when keys are unset (`tests/test_provider_registry.py:28-36`).
- **Observed:** Lookup still performs live HTTP to keyless providers unless the fixture backend is enabled (`stager_core/metadata/lookup.py:100-111`, `stager_core/metadata/fixture_providers.py:118-119`). Empty keys do **not** mean “offline mode.”
- **Observed:** `MetadataLookupService` uses `resolve_mam_id()` (broader than Stager-only bootstrap) when building `MetadataProviders` (`stager_core/metadata/lookup.py:92-110` vs `stager_core/metadata/providers.py:132-161`), but Compose only supplies `STAGER_MAM_ID` (`docker-compose.yml:21`).

### Understand project layout from README alone

- **Observed:** README table covers `app/`, `stager_core/`, `static/`, `tools/`, one doc (`README.md:39-47`).
- **Observed:** Rework notes exist under `docs/rework/` (this file); only `docs/pinning-model.md` is linked from README (`README.md:47`).
- **Observed:** `conftest.py:1-15` explains that `app` and `stager_core` live at repo root for pytest path setup — not stated in README.

### Run the full test suite as documented

- **Observed:** Default pytest excludes `e2e` (`pytest.ini:6-7`). README states e2e needs Playwright and Chromium (`README.md:37-38`) but does **not** document `playwright install` (no matches in repo except `pytest.ini:3`).
- **Observed:** Unit/integration tests need `requirements.txt` + dev deps in `tests/requirements-e2e.txt:1-5` (`README.md:33-34`), including `httpx` used only in e2e (`tests/e2e/conftest.py:13`).
- **Unknown:** Whether `py -3 -m pytest` passes on a clean machine after `pip install -r requirements.txt` only (no CI artifact; see Packaging inventory). Would need a local run log or CI job.

### Know license terms or project governance

- **Observed:** No `LICENSE` file in the repo root (glob search returned zero files).
- **Observed:** No `CONTRIBUTING*`, `CODE_OF_CONDUCT`, or `.github/workflows` (glob search).

### Rely on automated CI

- **Observed:** No `.github/` directory (glob search). Quality gates are undocumented for strangers.

---

## Packaging inventory

| Artifact | Present? | Path / notes |
|----------|----------|----------------|
| `pyproject.toml` | No | — |
| `requirements.txt` | Yes | `requirements.txt:1-5` — `fastapi`, `uvicorn[standard]`, `mutagen`, `apscheduler` |
| Test extras | Yes | `tests/requirements-e2e.txt:1-5` — `pytest`, `pytest-playwright`, `playwright`, `httpx` |
| `LICENSE` | No | — |
| GitHub Actions / other CI | No | No `.github/` tree |
| `Dockerfile` | Yes | `Dockerfile:1-16` — base `python:3.12-slim`, `CMD` uvicorn on port 8000 |
| `docker-compose.yml` | Yes | `docker-compose.yml:1-36` — service `audiobook-stager`, host port `AUDIOBOOK_STAGER_PORT` default 9570 |
| `.env.example` | Yes | `.env.example:1-23` |
| README quickstart | Yes | `README.md:7-35` — Docker-first; test section uses Windows `py -3` |
| `pytest.ini` | Yes | `pytest.ini:1-8` |
| Python version declared | Partial | **Observed:** `Dockerfile:1` pins `3.12-slim`. **Observed:** Not declared in `requirements.txt` or README. |

### Declared vs imported dependencies

**Declared in `requirements.txt:1-5`:**

- FastAPI (`fastapi>=0.115.0`)
- Uvicorn (`uvicorn[standard]>=0.32.0`)
- Mutagen (`mutagen>=1.47.0`)
- APScheduler (`apscheduler>=3.10.0`)

**Imported in application code (representative):**

| Dependency | Where | Declared in `requirements.txt`? |
|------------|--------|----------------------------------|
| FastAPI / Starlette | `app/main.py:6-10`, `app/api.py:15` | FastAPI yes; Starlette transitive |
| Pydantic | `app/api.py:16` | **Inference:** transitive via FastAPI, not pinned |
| APScheduler | `app/scheduler.py:6-7` | Yes |
| Mutagen | `stager_core/metadata/duration.py:12`, `stager_core/metadata/tags.py:86` | Yes |
| stdlib `urllib` HTTP client | `stager_core/metadata/ratelimit.py:7-9`, `188-213` | N/A |
| stdlib `sqlite3` | `app/db.py`, `stager_core/metadata/cache.py`, many tests | N/A |

**Test-only (not in main `requirements.txt`):**

- `pytest` — `pytest.ini`, `conftest.py`
- `playwright`, `pytest-playwright`, `httpx` — `tests/requirements-e2e.txt`, `tests/e2e/conftest.py`

---

## Personal-data classification table

Each row is a finding in the committed tree. **No secret values** are reproduced.

| Finding | Location | Classification |
|---------|----------|----------------|
| Default `BOOKS_ROOT` `/data/Dropbox/Books` | `stager_core/paths.py:11`, `.env.example:10`, `docker-compose.yml:13` | **Must become optional config** (example default encodes one operator’s layout) |
| Default `AUDIOBOOKS_ROOT` `/data/Audiobooks` | `stager_core/paths.py:18`, `.env.example:11`, `docker-compose.yml:14` | **Must become optional config** |
| `TZ=America/Denver` default | `.env.example:8`, `docker-compose.yml:12` | **Must become optional config** |
| Compose comment “Seedbox deployments build this repo from outside” | `docker-compose.yml:1` | **Safe to document** (deployment context, no credentials) |
| MAM cookie file name `mam.cookies` under config host | `.env.example:19-20`, `stager_core/metadata/providers.py:80-81`, `.gitignore:7` | **Safe to document** (filename convention + env vars) |
| VPN / seedbox / `mam-updater` comments in MAM resolution docstring | `stager_core/metadata/providers.py:73`, `137-139`, `.env.example:21` | **Safe to document** (architecture intent; no values) |
| Fallback paths `CONFIG_ROOT/state/mam.cookies`, `CONFIG_ROOT/audiobook-stager/mam.cookies` | `stager_core/metadata/providers.py:82-84`, `152-154` | **Must become optional config** (couples to unstated host apps) |
| User-Agent `SeedboxAudiobookStager/0.1` and contact email in UA | `stager_core/metadata/lookup.py:82-83`, `stager_core/metadata/ratelimit.py:55` | **Must become optional config** (operator-specific branding; blank email does not disable — see Credential behavior) |
| Env keys `MAM_ID`, `MAM_COOKIE_FILE`, `STAGER_MAM_COOKIE_FILE`, `CONFIG_ROOT` | `stager_core/metadata/providers.py:27-31`, `74-85`, `148-154` | **Safe to document** (names only; behavior varies by entrypoint) |
| Test-only drive paths `Z:\__no_stager_mam_cookies__`, `V:\tmp\stager.mam` | `tests/test_provider_registry.py:24`, `tests/test_mam_cookie_rotation.py:55` | **Safe to document** (synthetic paths in tests; not runtime defaults) |
| Auto-load of repo `.env` for research keys | `stager_core/metadata/providers.py:35-66` | **Must become optional config** (implicit config discovery surprises strangers) |

---

## Credential behavior (observed)

### Provider registry (UI / `list_provider_status` / `probe_provider` pre-check)

Definitions: `stager_core/metadata/provider_registry.py:6-11`.

| Provider | Requires key in registry? | “Configured” when unset? | Enabled when unset? |
|----------|---------------------------|--------------------------|---------------------|
| Audnexus | No (`:7`) | N/A | Yes (`:35`) |
| Audible | No (`:8`) | N/A | Yes |
| Open Library | No (`:9`) | N/A | Yes |
| Google Books | Yes; env `GOOGLE_BOOKS_API_KEY` (`:10`) | No if env empty (`:26`) | No (`:35`) |
| MAM | Yes; env key name `STAGER_MAM_ID` (`:11`) | Uses `resolve_stager_mam_id()` only (`:22-25`) — cookie file or `STAGER_MAM_ID`, **not** `MAM_ID` | No when not configured |

Pre-probe skip when key-gated and not configured: `stager_core/metadata/provider_registry.py:53-58` (message `"API key not configured"`).

### Runtime search / `MetadataProviders`

| Provider | Unset credential behavior (code path) | Citation |
|----------|--------------------------------------|----------|
| Google Books | `google_books_search` returns `[]` if `google_api_key` empty | `stager_core/metadata/providers.py:718-720` |
| Google Books probe | `("skipped", "API key not configured")` | `stager_core/metadata/providers.py:884-886` |
| MAM | `mam_search` returns `[]`; debug log cites STAGER naming | `stager_core/metadata/providers.py:490-492` |
| MAM probe | Skipped if `not self.mam_id` | `stager_core/metadata/providers.py:897-899` |
| MAM session resolution for lookup | `resolve_mam_id()` order: Stager cookie → `STAGER_MAM_ID` → `MAM_ID` → cookie files under `CONFIG_ROOT` | `stager_core/metadata/providers.py:132-161`, wired in `stager_core/metadata/lookup.py:92-110` |
| Audnexus / Audible / Open Library | No API key fields; probes issue real HTTP requests | `stager_core/metadata/providers.py:854-882` |

### `METADATA_CONTACT_EMAIL`

- **Observed:** Default when unset is the literal `"local-dev"`, not empty string (`stager_core/metadata/lookup.py:82-83`).
- **Observed:** Open Library search does not gate on email; requests proceed with the composed User-Agent (`stager_core/metadata/lookup.py:83-88`, `stager_core/metadata/providers.py:652-677`).
- **Inference:** Blank email in `.env` does **not** disable Open Library; it substitutes `local-dev` in the UA unless the env var is set to another value.

### Offline / fixture metadata (not in README quickstart)

- **Observed:** `STAGER_METADATA_BACKEND=fixture` swaps to `FixtureMetadataProviders` (`stager_core/metadata/fixture_providers.py:118-119`, `stager_core/metadata/lookup.py:100-102`).
- **Observed:** E2E harness sets fixture backend and fake keys (`tests/e2e/conftest.py:61-67`).

---

## Doc contradictions

| README claim | Code / other doc behavior | Citations |
|--------------|---------------------------|-----------|
| Library layout described as hardlinks into `Author/Title` | Staging uses `Author/Title` when series is empty; with series, `Author/Series/{index - }Title` | `README.md:3` vs `stager_core/staging.py:300-312`, `315-332` |
| Optional settings list includes `STAGER_MAM_ID` only | Code also supports `MAM_ID`, cookie files, `STAGER_MAM_COOKIE_FILE`, `CONFIG_ROOT` paths; Compose does not pass `MAM_ID` | `README.md:26` vs `stager_core/metadata/providers.py:132-161`, `docker-compose.yml:11-22` |
| Tests: `pip install -r requirements.txt -r tests/requirements-e2e.txt` | Default pytest excludes e2e; Playwright browser install step not documented | `README.md:33-38`, `pytest.ini:6-7` |
| Variable table mentions `STAGER_CONFIG_ROOT` set by Compose | `.env.example` uses `STAGER_CONFIG_HOST` for the bind mount; in-container root is `/config` via Compose | `README.md:20-23`, `.env.example:4-5`, `docker-compose.yml:15`, `30-31` |

---

## `.gitignore` coverage (observed)

From `.gitignore:1-8`:

| Pattern | Covered? |
|---------|----------|
| `.env` | Yes (`:1`) |
| `*.db` | Yes (`:6`) |
| `mam.cookies` | Yes (`:7`) — basename anywhere in tree (Git ignore rules) |
| `*.log` | Yes (`:8`) |

**Gaps (observed):**

- No generic `*.cookies`, `*cookie*`, or credential JSON patterns.
- **Inference:** Cookie files with names other than `mam.cookies` (e.g. paths set via `STAGER_MAM_COOKIE_FILE` / `MAM_COOKIE_FILE`) are not ignored by name unless operators add rules.

---

## Inference (labeled)

1. **Inference:** The repo is **runnable** by a stranger with Docker, a copied `.env`, and prepared `DATA_ROOT` / `STAGER_CONFIG_HOST`, but it is **not yet OSS-ready** for arbitrary contributors: no license, no CI, Docker-only quickstart, and defaults that encode one deployment (Dropbox under `/data`, Denver TZ, seedbox-oriented UA).
2. **Inference:** Provider **status UI** may show MAM as disabled when only `MAM_ID` is set, while **lookup** might still use MAM via `resolve_mam_id()` — because registry uses `resolve_stager_mam_id()` (`stager_core/metadata/provider_registry.py:22-25`) but lookup uses `resolve_mam_id()` (`stager_core/metadata/lookup.py:92`).
3. **Inference:** Strangers expecting “scan works fully offline” from empty API keys will still hit the public internet for Audnexus/Audible/Open Library unless they discover `STAGER_METADATA_BACKEND=fixture` from tests/e2e.
4. **Inference:** Pydantic/Starlette versions float with whatever `pip` resolves for `fastapi` because they are not pinned in `requirements.txt`.

---

## Unknowns

| Question | Why unknown | File(s) to inspect |
|----------|-------------|---------------------|
| Legal redistribution / modification rights | No `LICENSE` in tree | Would need `LICENSE` or README legal section |
| Whether default `pytest` (non-e2e) passes on clone | No CI log; audit did not execute pytest in this environment | Local run or future CI |
| Whether Docker healthcheck passes before `DATA_ROOT` contains expected subpaths | Not exercised in this audit | Runtime trial with empty `./data` |
| Intended public name for User-Agent / product string | Only “SeedboxAudiobookStager” in code | Owner decision; `stager_core/metadata/lookup.py:83` |
| Whether `docs/rework/*` besides this doc are meant to ship with the OSS release | Only `01-product-contract.md` and this file observed under `docs/rework/` | Owner docs policy |