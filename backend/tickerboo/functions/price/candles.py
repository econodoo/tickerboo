"""TB.CANDLES — last N bars as table [date, O, H, L, C, V].
   TB.RANGE  — bars between from_date and to_date."""
from tickerboo.functions.base import (
    FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT, PARAM_N,
)
from tickerboo.functions.registry import register
from tickerboo.utils.errors import NoDataError


@register
class Candles(FunctionPlugin):
    name = "CANDLES"
    category = "price"
    tier = "simple"
    description = "Returns last N bars as a table: [Date, Open, High, Low, Close, Volume]."
    examples = [
        '=TB.CANDLES("VNM")               → last 100 daily bars',
        '=TB.CANDLES("VNM", "1d", 500)    → last 500 daily bars',
        '=TB.CANDLES("VNM", "1w", 52)     → last 52 weekly bars (1 year)',
    ]
    params = [PARAM_TICKER, PARAM_TF, PARAM_N]
    output = "array"
    output_columns = ["date", "open", "high", "low", "close", "volume"]

    async def compute(self, ctx, *, ticker, tf="1d", n=100):
        candles = await ctx.candles(ticker, tf, n)
        if not candles:
            raise NoDataError(ticker, reason="no candle data found")
        return [c.to_list() for c in candles]


@register
class Range(FunctionPlugin):
    name = "RANGE"
    category = "price"
    tier = "simple"
    description = "Returns bars between from_date and to_date as a table."
    examples = [
        '=TB.RANGE("VNM", "1d", "2024-01-01", "2024-06-30")',
    ]
    params = [
        PARAM_TICKER,
        PARAM_TF,
        Param("from_date", "date", required=True, desc="Start date (inclusive)"),
        Param("to_date",   "date", default=None, desc="End date (inclusive). Default = today."),
    ]
    output = "array"
    output_columns = ["date", "open", "high", "low", "close", "volume"]

    async def compute(self, ctx, *, ticker, tf="1d", from_date=None, to_date=None):
        from tickerboo.db.session import fetch_all
        from tickerboo.utils.dates import date_to_iso
        from datetime import date as _date

        ticker = ticker.upper()
        if tf == "1w":
            # For weekly: get daily then ctx handles rolling
            # Use a large N approach — get all daily from from_date
            all_daily = await ctx.candles(ticker, "1d", 5000, to_date)
            from_str = date_to_iso(from_date) if from_date else "2000-01-01"
            filtered = [c for c in all_daily if c.date >= from_str]
            # Re-roll to weekly via context
            # Simplified: just return filtered daily for now
            # TODO: proper weekly roll with date filter
            return [c.to_list() for c in filtered]

        from_str = date_to_iso(from_date) if from_date else "2000-01-01"
        to_str = date_to_iso(to_date) if to_date else "2099-12-31"

        rows = await fetch_all(
            "SELECT * FROM daily_ohlcv WHERE symbol=? AND date>=? AND date<=? ORDER BY date",
            (ticker, from_str, to_str),
        )
        if not rows:
            raise NoDataError(ticker, from_date, reason="no data in range")

        return [
            [r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]]
            for r in rows
        ]
