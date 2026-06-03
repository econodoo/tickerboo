"""
TB.SNAPSHOT — complete ticker overview in one formula.

=TB.SNAPSHOT("VNM") → spills a table:
  [Close, Change%, RSI, MACD_Dir, Trend, ADX, Vol_Ratio, From_52H, Signal]

Perfect for dashboard sheets — one formula per ticker, horizontal spill.
"""
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER
from tickerboo.functions.registry import register


@register
class Snapshot(FunctionPlugin):
    name = "SNAPSHOT"
    category = "composite"
    tier = "simple"
    description = "Complete ticker overview: [Close, Change%, RSI14, MACD_Dir, Trend, ADX, Vol_Ratio, From_52H, Signal]"
    examples = [
        '=TB.SNAPSHOT("VNM") → [124500, -0.5, 62.8, "Bull", "Up", 19.8, 1.2, -4.2, "Neutral"]',
    ]
    params = [PARAM_TICKER]
    output = "array"
    output_columns = ["close", "chg%", "RSI14", "MACD", "trend", "ADX", "vol_ratio", "from_52H", "signal"]

    async def compute(self, ctx, *, ticker):
        # Fetch all needed values via ctx.call (reuses existing plugins)
        close = await _safe_call(ctx, "CLOSE", ticker=ticker)
        chg_pct = await _safe_call(ctx, "CHANGE_PCT", ticker=ticker)
        rsi = await _safe_call(ctx, "RSI", ticker=ticker, period=14)
        macd_hist = await _safe_call(ctx, "MACD_HIST", ticker=ticker)
        sma20 = await _safe_call(ctx, "SMA", ticker=ticker, period=20)
        sma50 = await _safe_call(ctx, "SMA", ticker=ticker, period=50)
        adx = await _safe_call(ctx, "ADX", ticker=ticker)
        vol = await _safe_call(ctx, "VOL", ticker=ticker)
        vol_ma = await _safe_call(ctx, "VOL_MA", ticker=ticker, period=20)
        from_high = await _safe_call(ctx, "FROM_HIGH52W", ticker=ticker)

        # Derived: MACD direction
        macd_dir = "Bull" if macd_hist and macd_hist > 0 else ("Bear" if macd_hist and macd_hist < 0 else "—")

        # Derived: trend (MA20 vs MA50)
        if sma20 and sma50:
            trend = "Up" if sma20 > sma50 else "Down"
        else:
            trend = "—"

        # Derived: volume ratio
        vol_ratio = round(vol / vol_ma, 1) if vol and vol_ma and vol_ma > 0 else None

        # Derived: composite signal
        signal = _compute_signal(rsi, macd_hist, sma20, sma50, adx)

        return [
            close,
            _r(chg_pct),
            _r(rsi),
            macd_dir,
            trend,
            _r(adx),
            vol_ratio,
            _r(from_high),
            signal,
        ]


@register
class SnapshotTable(FunctionPlugin):
    name = "SNAPSHOT_TABLE"
    category = "composite"
    tier = "advanced"
    description = "Multi-ticker snapshot — vertical table with headers. Pass comma-separated tickers."
    examples = [
        '=TB.SNAPSHOT_TABLE("VNM,FPT,HPG") → 4×9 table (header + 3 tickers)',
    ]
    params = [
        Param("tickers", "string", required=True, desc="Comma-separated tickers: VNM,FPT,HPG"),
    ]
    output = "array"
    output_columns = ["ticker", "close", "chg%", "RSI14", "MACD", "trend", "ADX", "vol_ratio", "from_52H", "signal"]

    async def compute(self, ctx, *, tickers):
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if not ticker_list:
            return []

        # Header row
        rows = [["Ticker", "Close", "Chg%", "RSI14", "MACD", "Trend", "ADX", "VolR", "52wH%", "Signal"]]

        for ticker in ticker_list:
            try:
                result = await ctx.call("SNAPSHOT", ticker=ticker)
                if isinstance(result, list):
                    rows.append([ticker] + result)
                else:
                    rows.append([ticker] + ["—"] * 9)
            except Exception:
                rows.append([ticker] + ["ERR"] * 9)

        return rows


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _safe_call(ctx, fn_name, **kwargs):
    """Call a function, return None on error."""
    try:
        result = await ctx.call(fn_name, **kwargs)
        return result
    except Exception:
        return None


def _r(v, decimals=1):
    """Round a value, return None if not a number."""
    if v is None:
        return None
    try:
        return round(float(v), decimals)
    except (TypeError, ValueError):
        return None


def _compute_signal(rsi, macd_hist, sma20, sma50, adx):
    """Compute a simple composite signal: Bullish / Bearish / Neutral."""
    score = 0

    # RSI
    if rsi is not None:
        if rsi > 60:
            score += 1
        elif rsi < 40:
            score -= 1

    # MACD histogram
    if macd_hist is not None:
        if macd_hist > 0:
            score += 1
        else:
            score -= 1

    # Trend (MA20 vs MA50)
    if sma20 is not None and sma50 is not None:
        if sma20 > sma50:
            score += 1
        else:
            score -= 1

    # ADX (trend strength bonus)
    if adx is not None and adx > 25:
        score = score * 2 if score != 0 else score  # amplify existing signal

    if score >= 2:
        return "Bullish"
    elif score <= -2:
        return "Bearish"
    return "Neutral"
