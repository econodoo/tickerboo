"""Volume indicators: OBV, AD, VOL_MA."""
import talib
import numpy as np
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last


@register
class OBV(FunctionPlugin):
    name = "OBV"
    category = "volume"
    tier = "simple"
    description = "On-Balance Volume — cumulative volume based on price direction."
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, 100)
        return safe_last(talib.OBV(d["close"], d["volume"]))


@register
class AD(FunctionPlugin):
    name = "AD"
    category = "volume"
    tier = "advanced"
    description = "Accumulation/Distribution Line."
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, 100)
        return safe_last(talib.AD(d["high"], d["low"], d["close"], d["volume"]))


@register
class VOL_MA(FunctionPlugin):
    name = "VOL_MA"
    category = "volume"
    tier = "simple"
    description = "Volume Moving Average — SMA of volume over N periods."
    params = [PARAM_TICKER, PARAM_TF,
              Param("period", "integer", default=20, min=2, max=200),
              PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=20, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 2)
        return safe_last(talib.SMA(d["volume"], timeperiod=period))
