from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

import app.api as api
from app.api import ScanManagerHolder, router
from app.auto import AutoRunManager, try_scheduled_tick
from app.db import connect, get_auto_settings
from app.routers.auto import bind as bind_auto
from app.routers.auto import router as auto_router
from app.routers.books import bind as bind_books
from app.routers.books import router as books_router
from app.routers.conflicts import bind as bind_conflicts
from app.routers.conflicts import router as conflicts_router
from app.routers.health import bind as bind_health
from app.routers.health import router as health_router
from app.routers.merges import bind as bind_merges
from app.routers.merges import router as merges_router
from app.routers.scan import bind as bind_scan
from app.routers.scan import router as scan_router
from app.scan import ScanManager
from app.scheduler import init_scheduler, shutdown_scheduler
from app.session import StagingSession
from app.settings import books_path, db_path, library_path
from stager_core.library_cache import bind_session_provider

# Built Vue app. `/` returns dist/index.html and `/static` serves that same build.
# The name stays STATIC_DIR because the pagination test compares index() to it.
STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

holder = ScanManagerHolder()
api.holder = holder
bind_health(holder)
bind_scan(holder)
bind_books(holder)
bind_conflicts(holder)
bind_merges(holder)
bind_auto(holder)
bind_session_provider(lambda: holder.session)

app = FastAPI(title="Audiobook Stager", version="0.1.136")


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(NoCacheMiddleware)
app.include_router(router)
app.include_router(health_router)
app.include_router(scan_router)
app.include_router(books_router)
app.include_router(conflicts_router)
app.include_router(merges_router)
app.include_router(auto_router)


@app.on_event("startup")
def startup() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    conn = connect(db_path())
    holder.conn = conn
    books = books_path()
    library = library_path()
    hydrated = StagingSession.try_hydrate_from_db(conn, books, library)
    holder.session = hydrated if hydrated is not None else StagingSession(books, library)
    if hydrated is None:
        holder.session.stale = True
    holder.manager = ScanManager(conn, books, library, holder.session)
    holder.auto_manager = AutoRunManager(conn, holder.manager, holder.session)

    def tick() -> None:
        if holder.auto_manager is not None:
            try_scheduled_tick(holder.auto_manager)

    holder.scheduler_tick = tick
    settings = get_auto_settings(conn)
    init_scheduler(tick, settings["interval_hours"])


@app.on_event("shutdown")
def shutdown() -> None:
    shutdown_scheduler()
    if holder.conn is not None:
        holder.conn.close()
        holder.conn = None
        holder.manager = None
        holder.auto_manager = None
        holder.session = None
        holder.scheduler_tick = None


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
