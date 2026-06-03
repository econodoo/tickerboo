"""
Metadata functions — ticker universe, data status, info.

TB.TICKERS()           → list all available ticker symbols
TB.LAST_DATE("VNM")    → latest available trading date
TB.TICKER_INFO("VNM")  → [name, exchange, industry, first_date, last_date, bars]
TB.DATA_STATUS()       → [tickers, total_bars, earliest, latest]
"""
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER
from tickerboo.functions.registry import register
from tickerboo.db.session import fetch_one, fetch_all


@register
class Tickers(FunctionPlugin):
    name = "TICKERS"
    category = "metadata"
    tier = "simple"
    description = "List all available ticker symbols. Returns vertical array for Excel spill."
    examples = ['=TB.TICKERS() → spills VNM, VCB, FPT, ...']
    params = [
        Param("exchange", "string", default=None,
              choices=["HSX", "HNX", "UPCOM", None],
              desc="Filter by exchange (optional)"),
    ]
    output = "array"
    output_columns = ["symbol"]

    async def compute(self, ctx, *, exchange=None):
        if exchange:
            rows = await fetch_all(
                "SELECT symbol FROM stocks WHERE exchange=? ORDER BY symbol",
                (exchange.upper(),),
            )
        else:
            rows = await fetch_all("SELECT symbol FROM stocks ORDER BY symbol")
        return [[r["symbol"]] for r in rows]


@register
class LastDate(FunctionPlugin):
    name = "LAST_DATE"
    category = "metadata"
    tier = "simple"
    description = "Latest available trading date for a ticker (or across all tickers if none specified)."
    examples = [
        '=TB.LAST_DATE("VNM") → "2025-12-01"',
        '=TB.LAST_DATE()       → "2025-12-01" (any ticker)',
    ]
    params = [
        Param("ticker", "string", default=None, desc="Ticker symbol (optional — omit for latest across all)"),
    ]
    output = "text"

    async def compute(self, ctx, *, ticker=None):
        if ticker:
            row = await fetch_one(
                "SELECT MAX(date) as d FROM daily_ohlcv WHERE symbol=?",
                (ticker.upper(),),
            )
        else:
            row = await fetch_one("SELECT MAX(date) as d FROM daily_ohlcv")
        return row["d"] if row and row["d"] else None


@register
class TickerInfo(FunctionPlugin):
    name = "TICKER_INFO"
    category = "metadata"
    tier = "simple"
    description = "Returns [name, exchange, industry, first_date, last_date, total_bars] for a ticker."
    examples = ['=TB.TICKER_INFO("VNM") → ["Vinamilk", "HSX", "Consumer Staples", "2024-01-02", "2025-12-01", 500]']
    params = [PARAM_TICKER]
    output = "array"
    output_columns = ["name", "exchange", "industry", "first_date", "last_date", "bars"]

    async def compute(self, ctx, *, ticker):
        row = await fetch_one(
            "SELECT name, exchange, industry, first_date, last_date, total_bars FROM stocks WHERE symbol=?",
            (ticker.upper(),),
        )
        if not row:
            from tickerboo.utils.errors import TickerNotFoundError
            raise TickerNotFoundError(f"Ticker '{ticker}' not found")
        return [row["name"], row["exchange"], row["industry"],
                row["first_date"], row["last_date"], row["total_bars"]]


@register
class DataStatus(FunctionPlugin):
    name = "DATA_STATUS"
    category = "metadata"
    tier = "simple"
    description = "Returns [total_tickers, total_bars, earliest_date, latest_date]."
    examples = ['=TB.DATA_STATUS() → [15, 7500, "2024-01-02", "2025-12-01"]']
    params = []
    output = "array"
    output_columns = ["tickers", "bars", "earliest", "latest"]

    async def compute(self, ctx):
        row = await fetch_one(
            """SELECT COUNT(DISTINCT symbol) as tickers, COUNT(*) as bars,
                      MIN(date) as earliest, MAX(date) as latest
               FROM daily_ohlcv"""
        )
        if not row:
            return [0, 0, None, None]
        return [row["tickers"], row["bars"], row["earliest"], row["latest"]]


@register
class BarCount(FunctionPlugin):
    name = "BAR_COUNT"
    category = "metadata"
    tier = "simple"
    description = "Number of available bars for a ticker."
    params = [PARAM_TICKER, Param("tf", "string", default="1d")]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d"):
        if tf == "1w":
            # Approximate: daily bars / 5
            row = await fetch_one(
                "SELECT COUNT(*) as n FROM daily_ohlcv WHERE symbol=?",
                (ticker.upper(),),
            )
            return (row["n"] // 5) if row else 0
        row = await fetch_one(
            "SELECT COUNT(*) as n FROM daily_ohlcv WHERE symbol=?",
            (ticker.upper(),),
        )
        return row["n"] if row else 0
