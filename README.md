# Audiobook Stager

Web app that scans a folder of audiobook seeds, looks up author and title, and hardlinks approved books into an `Author/Title` library.

The FastAPI app lives in `app/`. Discovery, staging, and metadata lookup live in `stager_core/`.

## Run

```powershell
Copy-Item .env.example .env
# Set DATA_ROOT to the host folder that contains your seeds and library.
docker compose up -d --build
```

The UI is at http://localhost:9570.

| Variable | Role |
|----------|------|
| `DATA_ROOT` | Host folder mounted at `/data` |
| `STAGER_CONFIG_HOST` | Host folder mounted at `/config` (database and cookie) |
| `BOOKS_ROOT` | Container path to scan |
| `AUDIOBOOKS_ROOT` | Container path for the hardlink library |
| `STAGER_CONFIG_ROOT` | Set to `/config` by Compose |
| `AUDIOBOOK_STAGER_PORT` | Host port (default 9570) |

Optional metadata settings: `GOOGLE_BOOKS_API_KEY`, `METADATA_CONTACT_EMAIL`, `AUDNEXUS_REGION`, `STAGER_MAM_ID`, `MAM_REQUESTS_PER_MINUTE`.

`BOOKS_ROOT` and `AUDIOBOOKS_ROOT` must sit on the same mount. Hardlinks fail across mounts.

## Test

```powershell
py -3 -m pip install -r requirements.txt -r tests/requirements-e2e.txt
py -3 -m pytest
```

End-to-end browser tests are marked `e2e` and are excluded by default. They need Playwright and Chromium.

## Layout

| Path | Purpose |
|------|---------|
| `app/` | FastAPI service, scan session, API |
| `stager_core/` | Discovery, staging, metadata |
| `static/` | Web UI |
| `tools/` | In-container diagnostics |
| `docs/pinning-model.md` | How manual and suggested metadata interact |
