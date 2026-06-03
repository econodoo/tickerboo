"""
SuperTrend — trend-following indicator using ATR.

Not in TA-Lib; custom implementation.
Returns (value, direction) where direction = +1 (bullish) or −1 (bearish).
"""
import numpy as np
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays


def _supertrend(high, low, close, period=10, multiplier=3.0):
    """Compute SuperTrend values and direction."""
    atr = talib.ATR(high, low, close, timeperiod=period)
    n = len(close)
    hl2 = (high + low) / 2

    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    supertrend = np.zeros(n)
    direction = np.ones(n)  # 1 = bullish, -1 = bearish

    for i in range(1, n):
        if np.isnan(atr[i]):
            supertrend[i] = np.nan
            continue

        # Adjust bands based on previous
        if lower[i] > lower[i - 1] or close[i - 1] < lower[i - 1]:
            pass  # keep current lower
        else:
            lower[i] = lower[i - 1]

        if upper[i] < upper[i - 1] or close[i - 1] > upper[i - 1]:
            pass  # keep current upper
        else:
            upper[i] = upper[i - 1]

        # Direction
        if supertrend[i - 1] == upper[i - 1]:
            # Was bearish
            if close[i] > upper[i]:
                supertrend[i] = lower[i]
                direction[i] = 1
            else:
                supertrend[i] = upper[i]
                direction[i] = -1
        else:
            # Was bullish
            if close[i] < lower[i]:
                supertrend[i] = upper[i]
                direction[i] = -1
            else:
                supertrend[i] = lower[i]
                direction[i] = 1

    return supertrend, direction


_PER  = Param("period",     "integer", default=10,  min=2,   max=200, desc="ATR period")
_MULT = Param("multiplier", "number",  default=3.0, min=0.5, max=10,  desc="ATR multiplier")


@register
class SUPERTREND(FunctionPlugin):
    name = "SUPERTREND"
    category = "composite"
    tier = "simple"
    description = "SuperTrend — returns [Value, Direction]. Direction: +1 bullish, −1 bearish."
    examples = ['=TB.SUPERTREND("VNM") → [85200.0, 1]']
    params = [PARAM_TICKER, PARAM_TF, _PER, _MULT, PARAM_AT]
    output = "array"
    output_columns = ["value", "direction"]

    async def compute(self, ctx, *, ticker, tf="1d", period=10, multiplier=3.0, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 5)
        st, dr = _supertrend(d["high"], d["low"], d["close"], period, multiplier)
        val = float(st[-1]) if not np.isnan(st[-1]) else None
        dirn = int(dr[-1])
        return [round(val, 2) if val else None, dirn]


@register
class SUPERTREND_VAL(FunctionPlugin):
    name = "SUPERTREND_VAL"
    category = "composite"
    tier = "simple"
    description = "SuperTrend value (the trend line price)."
    params = [PARAM_TICKER, PARAM_TF, _PER, _MULT, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=10, multiplier=3.0, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 5)
        st, _ = _supertrend(d["high"], d["low"], d["close"], period, multiplier)
        val = float(st[-1])
        return round(val, 2) if not np.isnan(val) else None


@register
class SUPERTREND_DIR(FunctionPlugin):
    name = "SUPERTREND_DIR"
    category = "composite"
    tier = "simple"
    description = "SuperTrend direction: +1 = bullish, −1 = bearish."
    params = [PARAM_TICKER, PARAM_TF, _PER, _MULT, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=10, multiplier=3.0, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 5)
        _, dr = _supertrend(d["high"], d["low"], d["close"], period, multiplier)
        return int(dr[-1])


@register
class PSAR(FunctionPlugin):
    name = "PSAR"
    category = "composite"
    tier = "advanced"
    description = "Parabolic SAR — stop-and-reverse trend indicator."
    params = [PARAM_TICKER, PARAM_TF,
              Param("accel", "number", default=0.02, desc="Acceleration factor"),
              Param("maximum", "number", default=0.2, desc="Maximum acceleration"),
              PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", accel=0.02, maximum=0.2, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, 60)
        from tickerboo.functions.helpers import safe_last
        return safe_last(talib.SAR(d["high"], d["low"], acceleration=accel, maximum=maximum))
