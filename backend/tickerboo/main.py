"""
TickerBoo — FastAPI application.

Startup sequence:
  1. Setup logging
  2. Warm asset version cache
  3. (Iter 1+) Init DB
  4. (Iter 4+) Start APScheduler

Access:
  Dev:  http://localhost:8688/health
  Prod: https://tmc.vetami.net/tb/health
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .assets import warm_asset_cache
from .config import settings
from .logging_setup import setup_logging

log = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    setup_logging(settings.log_path, settings.log_level)
    log.info("TickerBoo %s starting [env=%s]", settings.version, settings.env)

    warm_asset_cache()

    # Init DB (create tables if needed)
    from .db.session import init_db, close_db
    await init_db()

    # Discover all function plugins
    from .functions.registry import registry
    registry.discover()
    log.info("Functions registered: %d", registry.count)

    # Placeholder hooks for future:
    # from .jobs.scheduler import start_scheduler; start_scheduler()

    log.info("Startup complete — listening on %s:%s", settings.host, settings.port)
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    log.info("TickerBoo shutting down")
    await close_db()
    # from .jobs.scheduler import stop_scheduler; stop_scheduler()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TickerBoo",
    description="VN stock market data & analytics API for Excel/Sheets add-ins.",
    version=settings.version,
    root_path=settings.root_path,   # "/tb" in prod, "" in dev
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow Excel Online (office.com) and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://excel.officeapps.live.com",
        "https://*.officeapps.live.com",
        "https://tmc.vetami.net",
        "http://localhost:3000",     # addin dev server
        "http://localhost:8688",     # local backend
        "null",                      # file:// for offline sideloading
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (sidebar assets etc.)
from pathlib import Path
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    """Liveness check — returns immediately, no DB required."""
    return {
        "status": "ok",
        "version": settings.version,
        "env": settings.env,
    }


@app.get("/", tags=["system"], include_in_schema=False)
async def root():
    return {
        "message": "TickerBoo API",
        "docs": "/docs",
        "health": "/health",
        "playground": "/admin/playground",
    }


# ── Route groups ─────────────────────────────────────────────────────────────
from .api.functions import router as functions_router
from .api.admin import router as admin_router

app.include_router(functions_router)
app.include_router(admin_router)
