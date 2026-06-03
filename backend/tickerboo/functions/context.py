"""
ComputeContext — the interface plugins use to access data.

Every plugin.compute(ctx, **kwargs) receives a ctx that provides:
  - ctx.candles(ticker, tf, n, ending_at)   → list of candle dicts
  - ctx.candle_at(ticker, tf, at)           → single candle or None
  - ctx.call(fn_name, **args)               → result of another plugin
  - ctx.latest_date(ticker, tf)             → most recent bar date
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from tickerboo.db.session import fetch_one, fetch_all
from tickerboo.utils.dates import parse_at, date_to_iso, prev_weekday
from tickerboo.utils.errors import (
    NoDataError, TickerNotFoundError, TimeframeNotAvailable, InsufficientDataError
)

if TYPE_CHECKING:
    from tickerboo.functions.registry import _Registry

log = logging.getLogger(__name__)


@dataclass
class Candle:
    """Single OHLCV bar."""
    symbol: str
    date: str           # ISO date string
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_list(self) -> list:
        return [self.date, self.open, self.high, self.low, self.close, self.volume]


class ComputeContext:
    """
    Execution context for function plugins.

    Provides data access without plugins knowing about DB details.
    EoD-only for now — intraday methods raise TimeframeNotAvailable.
    """

    def __init__(self, registry: _Registry):
        self._registry = registry

    def _check_tf(self, tf: str):
        """Raise if timeframe is intraday (not yet supported)."""
        if tf in ("15m", "1h"):
            raise TimeframeNotAvailable(tf)

    async def candles(
        self,
        ticker: str,
        tf: str = "1d",
        n: int = 100,
        ending_at: date | datetime | None = None,
    ) -> list[Candle]:
        """
        Fetch N most recent candles for ticker/tf, ending at or before `ending_at`.

        Returns newest-last (chronological order).
        """
        self._check_tf(tf)
        ticker = ticker.upper().strip()

        if tf == "1w":
            return await self._weekly_candles(ticker, n, ending_at)

        # Daily candles
        if ending_at:
            at_str = date_to_iso(ending_at)
            rows = await fetch_all(
                "SELECT * FROM daily_ohlcv WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT ?",
                (ticker, at_str, n),
            )
        else:
            rows = await fetch_all(
                "SELECT * FROM daily_ohlcv WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (ticker, n),
            )

        if not rows:
            raise NoDataError(ticker, ending_at, reason="no candle data found")

        # Reverse to chronological (oldest first)
        rows.reverse()
        return [Candle(
            symbol=r["symbol"], date=r["date"],
            open=r["open"], high=r["high"], low=r["low"],
            close=r["close"], volume=r["volume"],
        ) for r in rows]

    async def candle_at(
        self,
        ticker: str,
        tf: str = "1d",
        at: date | datetime | None = None,
    ) -> Candle | None:
        """
        Get the single candle at (or nearest before) the given date.

        Returns None if no data exists.
        """
        self._check_tf(tf)
        ticker = ticker.upper().strip()

        if tf == "1w":
            candles = await self._weekly_candles(ticker, 1, at)
            return candles[0] if candles else None

        if at:
            at_str = date_to_iso(at)
            row = await fetch_one(
                "SELECT * FROM daily_ohlcv WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
                (ticker, at_str),
            )
        else:
            row = await fetch_one(
                "SELECT * FROM daily_ohlcv WHERE symbol=? ORDER BY date DESC LIMIT 1",
                (ticker,),
            )

        if not row:
            return None

        return Candle(
            symbol=row["symbol"], date=row["date"],
            open=row["open"], high=row["high"], low=row["low"],
            close=row["close"], volume=row["volume"],
        )

    async def latest_date(self, ticker: str, tf: str = "1d") -> str | None:
        """Get the most recent bar date for a ticker."""
        self._check_tf(tf)
        row = await fetch_one(
            "SELECT MAX(date) as max_date FROM daily_ohlcv WHERE symbol=?",
            (ticker.upper(),),
        )
        return row["max_date"] if row else None

    async def ticker_exists(self, ticker: str) -> bool:
        """Check if we have any data for this ticker."""
        row = await fetch_one(
            "SELECT 1 FROM daily_ohlcv WHERE symbol=? LIMIT 1",
            (ticker.upper(),),
        )
        return row is not None

    async def call(self, fn_name: str, **kwargs) -> Any:
        """Call another registered function (for shortcuts/composites)."""
        result = await self._registry.call(fn_name, kwargs, ctx=self)
        return result.get("value")

    # ── Weekly candle rolling ────────────────────────────────────────────────

    async def _weekly_candles(
        self, ticker: str, n: int, ending_at: date | datetime | None
    ) -> list[Candle]:
        """
        Roll daily candles into weekly OHLCV.

        Week = Monday to Friday. Uses daily_ohlcv grouped by ISO week.
        """
        # Fetch enough daily candles (roughly n*5 days for n weeks)
        daily = await self.candles(ticker, "1d", n * 7, ending_at)
        if not daily:
            return []

        # Group by ISO week (year, week_number)
        from collections import OrderedDict
        weeks: OrderedDict[tuple, list[Candle]] = OrderedDict()
        for c in daily:
            d = date.fromisoformat(c.date)
            key = d.isocalendar()[:2]  # (year, week)
            weeks.setdefault(key, []).append(c)

        # Roll each week into one candle
        result = []
        for (yr, wk), bars in weeks.items():
            # Monday of this ISO week
            from datetime import date as _date
            monday = _date.fromisocalendar(yr, wk, 1)
            result.append(Candle(
                symbol=ticker,
                date=monday.isoformat(),
                open=bars[0].open,
                high=max(b.high for b in bars),
                low=min(b.low for b in bars),
                close=bars[-1].close,
                volume=sum(b.volume for b in bars),
            ))

        # Return last n weeks, chronological
        return result[-n:]
