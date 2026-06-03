"""
Shared helpers for indicator plugins.

Every indicator needs: candles → numpy arrays → talib → last value.
This module provides the common extraction and validation.
"""
from __future__ import annotations

import math
import numpy as np
from tickerboo.utils.errors import InsufficientDataError


async def get_ohlcv_arrays(ctx, ticker: str, tf: str, at, lookback: int) -> dict:
    """
    Fetch candles and return numpy arrays.

    Returns dict with keys: open, high, low, close, volume (all np.float64).
    Raises InsufficientDataError if not enough bars.
    """
    candles = await ctx.candles(ticker, tf, n=lookback, ending_at=at)
    if len(candles) < 2:
        raise InsufficientDataError(ticker, lookback, len(candles))
    return {
        "open":   np.array([c.open for c in candles],   dtype=np.float64),
        "high":   np.array([c.high for c in candles],   dtype=np.float64),
        "low":    np.array([c.low for c in candles],     dtype=np.float64),
        "close":  np.array([c.close for c in candles],   dtype=np.float64),
        "volume": np.array([c.volume for c in candles],  dtype=np.float64),
    }


def safe_last(arr) -> float | None:
    """Return the last non-NaN value from a numpy array, or None."""
    if arr is None or len(arr) == 0:
        return None
    val = float(arr[-1])
    return None if math.isnan(val) else round(val, 4)
