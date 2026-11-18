from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import holder, router
from app.auto import AutoRunManager, try_scheduled_tick
from app.db import connect, get_auto_settings
from app.scan import ScanManager
from app.scheduler import init_scheduler, shutdown_scheduler
from app.session import StagingSession
from app.settings import books_path, db_path, library_path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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
