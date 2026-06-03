"""Bollinger Bands — composite + individual components."""
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last

_PER = Param("period", "integer", default=20, min=2, max=200, desc="Lookback period")
_STD = Param("stddev", "number",  default=2.0, min=0.1, max=5.0, desc="Standard deviation multiplier")


async def _compute_bb(ctx, ticker, tf, period, stddev, at):
    d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 2)
    upper, middle, lower = talib.BBANDS(
        d["close"], timeperiod=period, nbdevup=stddev, nbdevdn=stddev
    )
    return safe_last(upper), safe_last(middle), safe_last(lower), safe_last(d["close"])


@register
class BBANDS(FunctionPlugin):
    name = "BBANDS"
    category = "volatility"
    tier = "simple"
    description = "Bollinger Bands — returns [Upper, Middle, Lower]."
    examples = ['=TB.BBANDS("VNM") → [89500, 87200, 84900]']
    params = [PARAM_TICKER, PARAM_TF, _PER, _STD, PARAM_AT]
    output = "array"
    output_columns = ["upper", "middle", "lower"]

    async def compute(self, ctx, *, ticker, tf="1d", period=20, stddev=2.0, at=None):
        u, m, l, _ = await _compute_bb(ctx, ticker, tf, period, stddev, at)
        return [u, m, l]


@register
class BB_UPPER(FunctionPlugin):
    name = "BB_UPPER"
    category = "volatility"
    tier = "simple"
    description = "Bollinger upper band."
    params = [PARAM_TICKER, PARAM_TF, _PER, _STD, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=20, stddev=2.0, at=None):
        u, _, _, _ = await _compute_bb(ctx, ticker, tf, period, stddev, at)
        return u


@register
class BB_MIDDLE(FunctionPlugin):
    name = "BB_MIDDLE"
    category = "volatility"
    tier = "simple"
    description = "Bollinger middle band (SMA)."
    params = [PARAM_TICKER, PARAM_TF, _PER, _STD, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=20, stddev=2.0, at=None):
        _, m, _, _ = await _compute_bb(ctx, ticker, tf, period, stddev, at)
        return m


@register
class BB_LOWER(FunctionPlugin):
    name = "BB_LOWER"
    category = "volatility"
    tier = "simple"
    description = "Bollinger lower band."
    params = [PARAM_TICKER, PARAM_TF, _PER, _STD, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=20, stddev=2.0, at=None):
        _, _, l, _ = await _compute_bb(ctx, ticker, tf, period, stddev, at)
        return l


@register
class BB_WIDTH(FunctionPlugin):
    name = "BB_WIDTH"
    category = "volatility"
    tier = "advanced"
    description = "Bollinger Band Width — (upper − lower) / middle × 100."
    params = [PARAM_TICKER, PARAM_TF, _PER, _STD, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=20, stddev=2.0, at=None):
        u, m, l, _ = await _compute_bb(ctx, ticker, tf, period, stddev, at)
        if m and m > 0:
            return round((u - l) / m * 100, 4)
        return None


@register
class BB_PERCENT(FunctionPlugin):
    name = "BB_PERCENT"
    category = "volatility"
    tier = "advanced"
    description = "Bollinger %B — (price − lower) / (upper − lower). 0=at lower, 1=at upper."
    params = [PARAM_TICKER, PARAM_TF, _PER, _STD, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=20, stddev=2.0, at=None):
        u, _, l, price = await _compute_bb(ctx, ticker, tf, period, stddev, at)
        if u and l and (u - l) > 0 and price:
            return round((price - l) / (u - l), 4)
        return None
