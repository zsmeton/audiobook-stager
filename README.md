# Audiobook Stager

One operator, one machine. The app scans a local audiobook seed folder, looks up metadata, and hardlinks approved books into a library. There is no login.

The library layout is `Author/Series/Title`. A series index prefixes the title folder as `{index} - Title`. The folder is flat `Author/Title` when series is empty or pinned empty. See `docs/pinning-model.md` for how a pinned empty series is stored.

Python 3.12. Licensed under the GNU General Public License v3.0 only (GPL-3.0-only). See `LICENSE`.

`/` serves the built Vue app from `frontend/dist`. `static/app.js` and `static/index.html` are gone.

## Quickstart

Leave every API key and credential blank. Copy `.env.example` to `.env` and do not fill them in. Put your own audiobook files in `./data/seeds`. The library is `./data/library`.

Discovered audio suffixes are `.mp3`, `.mp4`, `.m4a`, `.m4b`, `.flac`, `.ogg`, `.opus`, `.wav`, `.aac`, and `.wma`.

```bash
cp .env.example .env
mkdir -p data/seeds data/library config
docker compose up -d --build
```

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force -Path data/seeds, data/library, config
docker compose up -d --build
```

The Compose service name is `audiobook-stager`. The UI is at the published host port, http://localhost:9570 by default (`AUDIOBOOK_STAGER_PORT`). On a first run the screen says “Scan your library to get started”. Click **Start Scan**. Audnexus, Audible, and Open Library run with nothing set. Google Books and MyAnonaMouse stay off while their values are empty. The scan still runs.

Compose bind-mounts `./data` (`DATA_ROOT`) at `/data`. Inside the container the defaults are `/data/seeds` and `/data/library`.

## Hardlinks

Approved books are hardlinks of the seed files. Hardlinks require the same filesystem.

In Docker, the seeds and the library must be on the same mount inside the container. The default Compose file keeps both on the single `/data` bind mount. A separate mount for either path makes the hardlink fail.

## Metadata providers

| Provider | Credential | When the value is empty |
|----------|------------|-------------------------|
| Audnexus | none | Runs |
| Audible | none | Runs |
| Open Library | none | Runs. A blank `METADATA_CONTACT_EMAIL` does not turn Open Library off |
| Google Books | `GOOGLE_BOOKS_API_KEY` | Stays off |
| MyAnonaMouse | `STAGER_MAM_ID`, then `MAM_ID` when `STAGER_MAM_ID` is empty | Stays off when both are empty |

`AUDNEXUS_REGION` and `MAM_REQUESTS_PER_MINUTE` are optional settings. This document does not explain how to obtain an API key or a tracker session.

## Configuration

| Variable | Role |
|----------|------|
| `DATA_ROOT` | Host folder mounted at `/data` (default `./data`) |
| `STAGER_CONFIG_HOST` | Host folder mounted at `/config` (database and local config, default `./config`) |
| `BOOKS_ROOT` | Container path to scan (default `/data/seeds`, host `./data/seeds`) |
| `AUDIOBOOKS_ROOT` | Container path for the hardlink library (default `/data/library`, host `./data/library`) |
| `STAGER_CONFIG_ROOT` | Compose sets this to `/config` |
| `AUDIOBOOK_STAGER_PORT` | Host port (default 9570), published to container port 8000 |
| `TZ` | Container timezone (default `UTC`) |
| `GOOGLE_BOOKS_API_KEY` | Optional. Empty keeps Google Books off |
| `STAGER_MAM_ID` | Optional. Empty skips this value |
| `MAM_ID` | Optional fallback used when `STAGER_MAM_ID` is empty. Empty keeps MyAnonaMouse off |
| `METADATA_CONTACT_EMAIL` | Optional. Blank does not turn Open Library off |
| `AUDNEXUS_REGION` | Optional (default `us`) |
| `MAM_REQUESTS_PER_MINUTE` | Optional (default 120) |

## UI

The Docker image copies `frontend/dist`. `npm` is not required to run the image. After a frontend change, rebuild the UI with `npm run build` in `frontend/`, then rebuild the image.

## Tests

Python 3.12. Runtime dependencies are in `requirements.txt` and `pyproject.toml`.

```powershell
py -3 -m pip install -r requirements.txt pytest
py -3 -m pytest
```

`pytest.ini` sets `addopts = -ra -m "not e2e"`, so that command skips end-to-end tests. End-to-end tests are `py -3 -m pytest -m e2e` and need Playwright. Install `tests/requirements-e2e.txt`, then install Chromium with `py -3 -m playwright install chromium`.

Sample audio in the tests is a tiny generated fixture, not a copyrighted book.

GitHub Actions runs `python -m pytest --ignore=tests/e2e` on push and pull request. The ignore flag keeps collection from importing `tests/e2e`, so the workflow does not install or run Playwright.

## Layout

| Path | Purpose |
|------|---------|
| `app/` | FastAPI service, scan session, API |
| `stager_core/` | Discovery, staging, metadata |
| `frontend/` | Vue UI. `frontend/dist` is what `/` serves |
| `tools/` | In-container diagnostics |
| `docs/pinning-model.md` | How manual and suggested metadata interact |
