"""
Admin routes — data sync management + playground.

  POST /admin/sync/full       → full historical CafeF sync
  POST /admin/sync/catchup    → incremental catchup
  GET  /admin/sync/status     → latest sync info
  GET  /admin/stats           → DB stats (row counts, last dates)
  GET  /admin/playground      → serves the playground HTML page
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse

from tickerboo.sources.cafef import CafeF
from tickerboo.db.session import fetch_one, fetch_all

log = logging.getLogger(__name__)

router = APIRouter()

# Singleton CafeF instance (reuses HTTP client)
_cafef = CafeF()


# ── Sync operations ─────────────────────────────────────────────────────────

@router.post("/admin/sync/full", tags=["admin"])
async def sync_full(background_tasks: BackgroundTasks):
    """
    Trigger full CafeF historical sync (background).

    Downloads the 'upto' ZIP (all tickers, all history). Takes 1-3 minutes.
    Check progress via GET /admin/sync/status.
    """
    background_tasks.add_task(_run_full_sync)
    return {"status": "started", "message": "Full sync running in background. Check /admin/sync/status."}


@router.post("/admin/sync/catchup", tags=["admin"])
async def sync_catchup(background_tasks: BackgroundTasks):
    """
    Incremental catchup — downloads missing days since last sync.
    """
    background_tasks.add_task(_run_catchup_sync)
    return {"status": "started", "message": "Catchup sync running. Check /admin/sync/status."}


@router.post("/admin/sync/full-blocking", tags=["admin"])
async def sync_full_blocking():
    """Full sync (blocking — waits for completion). Use for scripting/testing."""
    result = await _cafef.sync_full()
    return {"status": "completed", "result": result}


@router.get("/admin/sync/status", tags=["admin"])
async def sync_status():
    """Current sync status — used by landing page for live stats."""
    db_stats = await fetch_one(
        """SELECT COUNT(DISTINCT symbol) as tickers,
                  COUNT(*) as total_bars,
                  MIN(date) as earliest,
                  MAX(date) as latest
           FROM daily_ohlcv"""
    )
    last_sync = await fetch_one(
        "SELECT * FROM data_sync ORDER BY id DESC LIMIT 1"
    )
    return {
        "db": dict(db_stats) if db_stats else {},
        "last_sync": dict(last_sync) if last_sync else None,
    }


@router.post("/admin/seed", tags=["admin"])
async def seed_mock_data():
    """Seed DB with realistic mock data (15 tickers × 500 days). For dev/testing."""
    from tickerboo.sources.seeder import MockSeeder
    seeder = MockSeeder()
    result = await seeder.seed()
    return {"status": "completed", "result": result}


@router.post("/admin/sync/catchup-blocking", tags=["admin"])
async def sync_catchup_blocking():
    """Catchup sync (blocking)."""
    result = await _cafef.sync_catchup()
    return {"status": "completed", "result": result}


@router.get("/admin/sync/status", tags=["admin"])
async def sync_status():
    """Get the status of the most recent sync operation."""
    status = await _cafef.get_sync_status()

    # Also grab DB summary
    row = await fetch_one(
        """SELECT COUNT(DISTINCT symbol) as tickers,
                  COUNT(*) as total_bars,
                  MIN(date) as earliest,
                  MAX(date) as latest
           FROM daily_ohlcv"""
    )
    return {
        "sync": status,
        "db": dict(row) if row else {},
    }


# ── DB stats ─────────────────────────────────────────────────────────────────

@router.get("/admin/stats", tags=["admin"])
async def db_stats():
    """Database statistics — row counts, date ranges, top tickers."""
    overview = await fetch_one(
        """SELECT COUNT(DISTINCT symbol) as tickers,
                  COUNT(*) as total_bars,
                  MIN(date) as earliest,
                  MAX(date) as latest
           FROM daily_ohlcv"""
    )

    # Top 10 tickers by total bars
    top = await fetch_all(
        "SELECT symbol, total_bars, first_date, last_date FROM stocks ORDER BY total_bars DESC LIMIT 10"
    )

    # Sync history
    syncs = await fetch_all(
        "SELECT * FROM data_sync ORDER BY id DESC LIMIT 5"
    )

    return {
        "overview": dict(overview) if overview else {},
        "top_tickers": [dict(r) for r in top],
        "recent_syncs": [dict(r) for r in syncs],
    }


@router.get("/admin/analytics", tags=["admin"])
async def analytics():
    """Function call analytics — most-used functions, recent calls, performance."""
    # Most-called functions
    top_fns = await fetch_all(
        """SELECT function_name, COUNT(*) as calls,
                  ROUND(AVG(duration_ms), 1) as avg_ms,
                  ROUND(MAX(duration_ms), 1) as max_ms
           FROM function_calls
           GROUP BY function_name
           ORDER BY calls DESC
           LIMIT 20"""
    )

    # Most-queried tickers
    top_tickers = await fetch_all(
        """SELECT ticker, COUNT(*) as calls
           FROM function_calls
           WHERE ticker IS NOT NULL
           GROUP BY ticker
           ORDER BY calls DESC
           LIMIT 10"""
    )

    # Recent calls
    recent = await fetch_all(
        """SELECT function_name, ticker, timeframe,
                  ROUND(duration_ms, 1) as ms, called_at
           FROM function_calls
           ORDER BY id DESC
           LIMIT 20"""
    )

    # Totals
    totals = await fetch_one(
        """SELECT COUNT(*) as total_calls,
                  ROUND(AVG(duration_ms), 1) as avg_ms,
                  COUNT(DISTINCT function_name) as unique_fns,
                  COUNT(DISTINCT ticker) as unique_tickers
           FROM function_calls"""
    )

    return {
        "totals": dict(totals) if totals else {},
        "top_functions": [dict(r) for r in top_fns],
        "top_tickers": [dict(r) for r in top_tickers],
        "recent_calls": [dict(r) for r in recent],
    }


# ── Playground ───────────────────────────────────────────────────────────────

@router.get("/admin/playground", tags=["admin"], response_class=HTMLResponse)
async def playground():
    """Serve the admin playground page."""
    html_path = Path(__file__).parent.parent / "static" / "playground.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Playground not found</h1><p>Run build first.</p>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ── Background task helpers ──────────────────────────────────────────────────

async def _run_full_sync():
    try:
        await _cafef.sync_full()
    except Exception:
        log.exception("Background full sync failed")


async def _run_catchup_sync():
    try:
        await _cafef.sync_catchup()
    except Exception:
        log.exception("Background catchup sync failed")
