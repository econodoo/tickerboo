"""TB.ATR — Average True Range, TB.NATR — Normalized ATR (%)."""
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last

_PER = Param("period", "integer", default=14, min=2, max=200, desc="Lookback period")


@register
class ATR(FunctionPlugin):
    name = "ATR"
    category = "volatility"
    tier = "simple"
    description = "Average True Range — measures volatility in price units."
    examples = ['=TB.ATR("VNM") → 1250.0']
    params = [PARAM_TICKER, PARAM_TF, _PER, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 3)
        return safe_last(talib.ATR(d["high"], d["low"], d["close"], timeperiod=period))


@register
class NATR(FunctionPlugin):
    name = "NATR"
    category = "volatility"
    tier = "advanced"
    description = "Normalized ATR — volatility as % of price."
    params = [PARAM_TICKER, PARAM_TF, _PER, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 3)
        return safe_last(talib.NATR(d["high"], d["low"], d["close"], timeperiod=period))
