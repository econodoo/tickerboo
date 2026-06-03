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


# ── Series endpoint ──────────────────────────────────────────────────────────

class SeriesRequest(BaseModel):
    args: dict[str, Any] = {}     # function arguments (ticker, tf, period, etc.)
    n: int = 200                  # number of bars


@router.post("/series/{name}", tags=["functions"])
async def function_series(name: str, req: SeriesRequest):
    """
    Compute indicator values for all bars in range.

    Returns [{time, value}] array (or [{time, ...cols}] for multi-output).
    Useful for charting, Excel array output, time series analysis.
    """
    import math
    import numpy as np

    plugin = registry.get(name)
    if plugin is None:
        return {"status": "error", "code": "not_found", "message": f"Function '{name}' not found"}

    try:
        validated = plugin.validate_params(req.args)
    except ValueError as e:
        return {"status": "error", "code": "invalid_param", "message": str(e)}

    ticker = validated.get("ticker", "")
    tf = validated.get("tf", "1d")

    # Fetch candles
    from tickerboo.functions.context import ComputeContext
    ctx = ComputeContext(registry=registry)

    try:
        candles = await ctx.candles(ticker, tf, req.n)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    if not candles:
        return {"status": "no_data", "message": f"No candle data for {ticker}"}

    # Compute full series using TA-Lib directly
    try:
        import talib
        closes = np.array([c.close for c in candles], dtype=np.float64)
        highs = np.array([c.high for c in candles], dtype=np.float64)
        lows = np.array([c.low for c in candles], dtype=np.float64)
        volumes = np.array([c.volume for c in candles], dtype=np.float64)

        fn_upper = name.upper()
        period = validated.get("period", 14)
        series = []

        # Map function name to TA-Lib computation
        talib_map = {
            "SMA": lambda: talib.SMA(closes, timeperiod=period),
            "EMA": lambda: talib.EMA(closes, timeperiod=period),
            "WMA": lambda: talib.WMA(closes, timeperiod=period),
            "DEMA": lambda: talib.DEMA(closes, timeperiod=period),
            "TEMA": lambda: talib.TEMA(closes, timeperiod=period),
            "RSI": lambda: talib.RSI(closes, timeperiod=period),
            "CCI": lambda: talib.CCI(highs, lows, closes, timeperiod=period),
            "MFI": lambda: talib.MFI(highs, lows, closes, volumes, timeperiod=period),
            "ADX": lambda: talib.ADX(highs, lows, closes, timeperiod=period),
            "ATR": lambda: talib.ATR(highs, lows, closes, timeperiod=period),
            "NATR": lambda: talib.NATR(highs, lows, closes, timeperiod=period),
            "WILLR": lambda: talib.WILLR(highs, lows, closes, timeperiod=period),
            "ROC": lambda: talib.ROC(closes, timeperiod=period),
            "MOM": lambda: talib.MOM(closes, timeperiod=period),
            "OBV": lambda: talib.OBV(closes, volumes),
        }

        if fn_upper in talib_map:
            arr = talib_map[fn_upper]()
            for i, c in enumerate(candles):
                v = float(arr[i])
                if not math.isnan(v):
                    series.append({"time": c.date, "value": round(v, 4)})
        elif fn_upper in ("MACD", "MACD_LINE", "MACD_SIGNAL", "MACD_HIST"):
            fast = validated.get("fast", 12)
            slow = validated.get("slow", 26)
            signal = validated.get("signal", 9)
            macd, sig, hist = talib.MACD(closes, fastperiod=fast, slowperiod=slow, signalperiod=signal)
            for i, c in enumerate(candles):
                if not math.isnan(float(macd[i])):
                    series.append({
                        "time": c.date,
                        "macd": round(float(macd[i]), 4),
                        "signal": round(float(sig[i]), 4),
                        "histogram": round(float(hist[i]), 4),
                    })
        elif fn_upper in ("BBANDS", "BB_UPPER", "BB_MIDDLE", "BB_LOWER"):
            bbperiod = validated.get("period", 20)
            stddev = validated.get("stddev", 2.0)
            upper, middle, lower = talib.BBANDS(closes, timeperiod=bbperiod, nbdevup=stddev, nbdevdn=stddev)
            for i, c in enumerate(candles):
                if not math.isnan(float(upper[i])):
                    series.append({
                        "time": c.date,
                        "upper": round(float(upper[i]), 4),
                        "middle": round(float(middle[i]), 4),
                        "lower": round(float(lower[i]), 4),
                    })
        elif fn_upper in ("STOCH", "STOCH_K", "STOCH_D"):
            k = validated.get("k", 14)
            d = validated.get("d", 3)
            sk, sd = talib.STOCH(highs, lows, closes, fastk_period=k, slowk_period=d, slowd_period=d)
            for i, c in enumerate(candles):
                if not math.isnan(float(sk[i])):
                    series.append({"time": c.date, "k": round(float(sk[i]), 4), "d": round(float(sd[i]), 4)})
        else:
            # Fallback: just return candle close prices as series
            series = [{"time": c.date, "value": c.close} for c in candles]

        return {
            "status": "ok",
            "function": fn_upper,
            "ticker": ticker,
            "timeframe": tf,
            "count": len(series),
            "series": series,
        }

    except Exception as e:
        log.exception("Series computation failed for %s", name)
        return {"status": "error", "message": str(e)}


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
