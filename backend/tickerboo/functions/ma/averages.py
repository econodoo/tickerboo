"""TB.SMA — Simple Moving Average, TB.EMA — Exponential Moving Average."""
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last

_PERIOD = Param("period", "integer", required=True, min=2, max=500, desc="Number of periods")


@register
class SMA(FunctionPlugin):
    name = "SMA"
    category = "ma"
    tier = "simple"
    description = "Simple Moving Average"
    examples = ['=TB.SMA("VNM", "1d", 20) → 86450.0']
    params = [PARAM_TICKER, PARAM_TF, _PERIOD, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=20, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 2)
        return safe_last(talib.SMA(d["close"], timeperiod=period))


@register
class EMA(FunctionPlugin):
    name = "EMA"
    category = "ma"
    tier = "simple"
    description = "Exponential Moving Average"
    examples = ['=TB.EMA("VNM", "1d", 20) → 86800.0']
    params = [PARAM_TICKER, PARAM_TF, _PERIOD, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=20, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 3)
        return safe_last(talib.EMA(d["close"], timeperiod=period))


@register
class WMA(FunctionPlugin):
    name = "WMA"
    category = "ma"
    tier = "advanced"
    description = "Weighted Moving Average"
    params = [PARAM_TICKER, PARAM_TF, _PERIOD, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=20, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 2)
        return safe_last(talib.WMA(d["close"], timeperiod=period))


@register
class DEMA(FunctionPlugin):
    name = "DEMA"
    category = "ma"
    tier = "advanced"
    description = "Double Exponential Moving Average"
    params = [PARAM_TICKER, PARAM_TF, _PERIOD, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=20, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 3)
        return safe_last(talib.DEMA(d["close"], timeperiod=period))


@register
class TEMA(FunctionPlugin):
    name = "TEMA"
    category = "ma"
    tier = "advanced"
    description = "Triple Exponential Moving Average"
    params = [PARAM_TICKER, PARAM_TF, _PERIOD, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=20, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 4)
        return safe_last(talib.TEMA(d["close"], timeperiod=period))
