"""
TB.SCREEN — scan all tickers for technical conditions.

  =TB.SCREEN("RSI<30")                 → oversold tickers
  =TB.SCREEN("RSI<30 AND CLOSE>MA50")  → oversold + above long MA
  =TB.SCREEN("CHANGE_PCT>3")           → up more than 3% today
  =TB.SCREEN("MA20>MA50 AND ADX>25")   → uptrend + strong trend
  =TB.SCREEN("FROM_HIGH52W>-5")        → within 5% of 52-week high

Supported tokens:
  Indicators: RSI, RSI7, RSI14, RSI21, SMA/MA+period, EMA+period,
              MACD_LINE, MACD_HIST, ADX, CCI, MFI, ATR, NATR,
              STOCH_K, STOCH_D, BB_UPPER, BB_LOWER, BB_PERCENT,
              OBV, WILLR, ROC, SUPERTREND_DIR
  Price:      CLOSE, OPEN, HIGH, LOW, VOL, CHANGE, CHANGE_PCT,
              HIGH52W, LOW52W, FROM_HIGH52W, FROM_LOW52W, BAR_COUNT
  Operators:  <  >  <=  >=  =
  Logic:      AND  OR
  Values:     any number (30, 0.5, -10, 1.5e6)
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from tickerboo.functions.base import FunctionPlugin, Param
from tickerboo.functions.registry import register
from tickerboo.functions.context import ComputeContext
from tickerboo.db.session import fetch_all

log = logging.getLogger(__name__)


# ── Indicator shorthand → function call mapping ─────────────────────────────

def _parse_indicator(token: str) -> tuple[str, dict]:
    """Map a shorthand token to (function_name, extra_params).

    Examples:
      "RSI"    → ("RSI", {})
      "RSI7"   → ("RSI", {"period": 7})
      "MA20"   → ("SMA", {"period": 20})
      "EMA50"  → ("EMA", {"period": 50})
      "CLOSE"  → ("CLOSE", {})
    """
    t = token.upper().strip()

    # Direct function names (no params)
    direct = {
        "CLOSE", "OPEN", "HIGH", "LOW", "VOL", "PRICE",
        "CHANGE", "CHANGE_PCT", "HIGH52W", "LOW52W",
        "FROM_HIGH52W", "FROM_LOW52W", "BAR_COUNT",
        "MACD_LINE", "MACD_SIGNAL", "MACD_HIST",
        "ADX", "CCI", "MFI", "ATR", "NATR",
        "STOCH_K", "STOCH_D", "OBV", "WILLR", "ROC", "MOM",
        "BB_UPPER", "BB_LOWER", "BB_MIDDLE", "BB_PERCENT", "BB_WIDTH",
        "SUPERTREND_DIR", "PSAR",
        "TENKAN", "KIJUN", "SENKOU_A", "SENKOU_B",
    }
    if t in direct:
        return t, {}

    # RSI + period
    m = re.match(r"^RSI(\d+)$", t)
    if m:
        return "RSI", {"period": int(m.group(1))}
    if t == "RSI":
        return "RSI", {"period": 14}

    # SMA/MA + period
    m = re.match(r"^(?:SMA|MA)(\d+)$", t)
    if m:
        return "SMA", {"period": int(m.group(1))}

    # EMA + period
    m = re.match(r"^EMA(\d+)$", t)
    if m:
        return "EMA", {"period": int(m.group(1))}

    # WMA + period
    m = re.match(r"^WMA(\d+)$", t)
    if m:
        return "WMA", {"period": int(m.group(1))}

    # MFI + period
    if t == "MFI":
        return "MFI", {"period": 14}
    m = re.match(r"^MFI(\d+)$", t)
    if m:
        return "MFI", {"period": int(m.group(1))}

    # VOL_MA
    m = re.match(r"^VOL_MA(\d*)$", t)
    if m:
        p = int(m.group(1)) if m.group(1) else 20
        return "VOL_MA", {"period": p}
    if t == "VOL_MA":
        return "VOL_MA", {"period": 20}

    raise ValueError(f"Unknown indicator: {token}")


# ── Condition parser ─────────────────────────────────────────────────────────

@dataclass
class Condition:
    left: str           # indicator token or number
    op: str             # <, >, <=, >=, =
    right: str          # indicator token or number

    def __str__(self):
        return f"{self.left} {self.op} {self.right}"


def _parse_conditions(expr: str) -> list[tuple[str, Condition]]:
    """Parse 'RSI<30 AND MA20>MA50' into [(logic, Condition), ...]"""
    # Normalize
    expr = expr.strip()
    if not expr:
        raise ValueError("Empty screen expression")

    # Split by AND/OR (preserve the operator)
    parts = re.split(r"\s+(AND|OR)\s+", expr, flags=re.IGNORECASE)

    conditions = []
    logic = "AND"  # first condition has implicit AND

    for part in parts:
        up = part.strip().upper()
        if up in ("AND", "OR"):
            logic = up
            continue

        # Parse "LEFT OP RIGHT"
        m = re.match(r"^(.+?)\s*(<=|>=|<|>|=)\s*(.+)$", part.strip())
        if not m:
            raise ValueError(f"Cannot parse condition: '{part}'. Expected 'INDICATOR OP VALUE'")

        conditions.append((logic, Condition(
            left=m.group(1).strip(),
            op=m.group(2),
            right=m.group(3).strip(),
        )))
        logic = "AND"  # reset to default

    return conditions


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ── Evaluation ───────────────────────────────────────────────────────────────

async def _eval_token(token: str, ticker: str, ctx: ComputeContext, registry) -> float | None:
    """Evaluate a token for a ticker. Returns float or None on error."""
    if _is_number(token):
        return float(token)

    try:
        fn_name, extra_params = _parse_indicator(token)
        params = {"ticker": ticker, "tf": "1d", **extra_params}
        result = await registry.call(fn_name, params, ctx=ctx)
        v = result.get("value")
        if v is None:
            return None
        if isinstance(v, list):
            return v[0] if v else None  # take first element of array
        return float(v)
    except Exception:
        return None


def _compare(left: float | None, op: str, right: float | None) -> bool:
    """Compare two values with operator."""
    if left is None or right is None:
        return False
    if op == "<":
        return left < right
    elif op == ">":
        return left > right
    elif op == "<=":
        return left <= right
    elif op == ">=":
        return left >= right
    elif op == "=":
        return abs(left - right) < 0.0001
    return False


async def _screen_ticker(
    ticker: str, conditions: list[tuple[str, Condition]],
    ctx: ComputeContext, registry,
) -> dict | None:
    """Evaluate all conditions for one ticker. Returns values dict or None."""
    values = {}
    overall = True

    for logic, cond in conditions:
        left_val = await _eval_token(cond.left, ticker, ctx, registry)
        right_val = await _eval_token(cond.right, ticker, ctx, registry)

        passed = _compare(left_val, cond.op, right_val)

        if logic == "AND":
            overall = overall and passed
        else:  # OR
            overall = overall or passed

        # Store values for display
        if not _is_number(cond.left):
            values[cond.left] = left_val
        if not _is_number(cond.right):
            values[cond.right] = right_val

    if overall:
        return {"ticker": ticker, **values}
    return None


# ── Plugin ───────────────────────────────────────────────────────────────────

@register
class Screen(FunctionPlugin):
    name = "SCREEN"
    category = "screen"
    tier = "advanced"
    description = "Scan all tickers for technical conditions. Returns matching tickers with indicator values."
    examples = [
        '=TB.SCREEN("RSI<30")               → oversold tickers',
        '=TB.SCREEN("CHANGE_PCT>3")          → up >3% today',
        '=TB.SCREEN("MA20>MA50 AND ADX>25")  → uptrend + strong',
        '=TB.SCREEN("FROM_HIGH52W>-5")       → near 52-week high',
    ]
    params = [
        Param("expr", "string", required=True,
              desc="Condition expression. Examples: 'RSI<30', 'MA20>MA50 AND ADX>25'"),
        Param("exchange", "string", default=None,
              desc="Filter universe: HSX, HNX, UPCOM (default: all)"),
    ]
    output = "array"
    cacheable = False

    async def compute(self, ctx, *, expr, exchange=None):
        from tickerboo.functions.registry import registry as reg

        # Parse conditions
        conditions = _parse_conditions(expr)

        # Get ticker universe
        if exchange:
            tickers = await fetch_all(
                "SELECT symbol FROM stocks WHERE exchange=? ORDER BY symbol",
                (exchange.upper(),),
            )
        else:
            tickers = await fetch_all("SELECT symbol FROM stocks ORDER BY symbol")

        if not tickers:
            return []

        # Screen each ticker
        t0 = time.perf_counter()
        results = []
        for row in tickers:
            ticker = row["symbol"]
            match = await _screen_ticker(ticker, conditions, ctx, reg)
            if match:
                results.append(match)

        duration = time.perf_counter() - t0
        log.info(
            "SCREEN '%s': %d/%d matched in %.1fs",
            expr, len(results), len(tickers), duration,
        )

        if not results:
            return []

        # Format as 2D array: [ticker, val1, val2, ...]
        # Header = ticker + all indicator names from conditions
        indicators = []
        for _, cond in conditions:
            if not _is_number(cond.left) and cond.left.upper() not in [i.upper() for i in indicators]:
                indicators.append(cond.left.upper())
            if not _is_number(cond.right) and cond.right.upper() not in [i.upper() for i in indicators]:
                indicators.append(cond.right.upper())

        rows = []
        for r in results:
            row = [r["ticker"]]
            for ind in indicators:
                v = r.get(ind)
                row.append(round(v, 2) if isinstance(v, (int, float)) and v is not None else v)
            rows.append(row)

        return rows
