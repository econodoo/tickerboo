"""
API routes for TB.* function dispatch.

  GET  /functions              → list all functions (with optional ?category= &tier= filter)
  GET  /functions/{name}       → schema for one function
  POST /call                   → generic dispatch {fn, args}
  POST /call/{name}            → dispatch with name in URL, args in body
  GET  /categories             → list categories with counts
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from typing import Any, Optional

from tickerboo.functions.registry import registry
from tickerboo.utils.errors import TickerBooError

log = logging.getLogger(__name__)

router = APIRouter()


class CallRequest(BaseModel):
    fn: Optional[str] = None      # function name (if not in URL)
    args: dict[str, Any] = {}     # function arguments


class CallResponse(BaseModel):
    status: str
    function: Optional[str] = None
    value: Any = None
    duration_ms: Optional[float] = None
    code: Optional[str] = None
    message: Optional[str] = None


# ── Function listing ─────────────────────────────────────────────────────────

@router.get("/functions", tags=["functions"])
async def list_functions(
    category: str | None = Query(None, description="Filter by category"),
    tier: str | None = Query(None, description="Filter by tier: simple, advanced, experimental"),
):
    """List all registered TB.* functions."""
    return {
        "count": registry.count,
        "functions": registry.list_all(category=category, tier=tier),
    }


@router.get("/functions/{name}", tags=["functions"])
async def get_function(name: str):
    """Get full schema for one function."""
    plugin = registry.get(name)
    if plugin is None:
        return {"status": "error", "code": "not_found", "message": f"Function '{name}' not found"}
    return {"status": "ok", "function": plugin.to_dict()}


@router.get("/categories", tags=["functions"])
async def list_categories():
    """List function categories with counts."""
    return {"categories": registry.categories()}


# ── Generic dispatch ─────────────────────────────────────────────────────────

@router.post("/call", tags=["functions"])
async def call_function(req: CallRequest):
    """
    Call any TB.* function by name.

    Body: {"fn": "RSI", "args": {"ticker": "VNM", "tf": "1d", "period": 14}}
    """
    if not req.fn:
        return {"status": "error", "code": "missing_fn", "message": "Provide 'fn' (function name)"}

    try:
        result = await registry.call(req.fn, req.args)
        return result
    except TickerBooError as e:
        return e.to_dict()


@router.post("/call/{name}", tags=["functions"])
async def call_function_by_name(name: str, req: CallRequest):
    """
    Call a specific function.

    URL provides function name, body provides args only.
    Body: {"args": {"ticker": "VNM", "tf": "1d"}}
    """
    try:
        result = await registry.call(name, req.args)
        return result
    except TickerBooError as e:
        return e.to_dict()


# ── Tickers listing ──────────────────────────────────────────────────────────

@router.get("/tickers", tags=["market"])
async def list_tickers(
    exchange: str | None = Query(None, description="Filter by exchange: HSX, HNX, UPCOM"),
    q: str | None = Query(None, description="Search by symbol prefix"),
):
    """List all available tickers (derived from CafeF data)."""
    from tickerboo.db.session import fetch_all

    conditions = []
    params = []

    if exchange:
        conditions.append("exchange = ?")
        params.append(exchange.upper())
    if q:
        conditions.append("symbol LIKE ?")
        params.append(f"{q.upper()}%")

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = await fetch_all(
        f"SELECT symbol, name, exchange, first_date, last_date, total_bars FROM stocks WHERE {where} ORDER BY symbol",
        tuple(params),
    )
    return {"count": len(rows), "tickers": rows}
