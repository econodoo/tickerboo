"""TB.OHLCV — returns [Open, High, Low, Close, Volume] for one bar.
   TB.OHLC  — returns [Open, High, Low, Close] (no volume)."""
from tickerboo.functions.base import FunctionPlugin, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.utils.errors import NoDataError


@register
class OHLCV(FunctionPlugin):
    name = "OHLCV"
    category = "price"
    tier = "simple"
    description = "Returns [Open, High, Low, Close, Volume] for one bar as a 1×5 array."
    examples = [
        '=TB.OHLCV("VNM")           → spills [87000, 88000, 86500, 87500, 1234567]',
        '=TB.OHLCV("VNM", "1w")     → weekly OHLCV',
    ]
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "array"
    output_columns = ["open", "high", "low", "close", "volume"]

    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        candle = await ctx.candle_at(ticker, tf, at)
        if candle is None:
            raise NoDataError(ticker, at, reason="no trading data")
        return [candle.open, candle.high, candle.low, candle.close, candle.volume]


@register
class OHLC(FunctionPlugin):
    name = "OHLC"
    category = "price"
    tier = "simple"
    description = "Returns [Open, High, Low, Close] for one bar as a 1×4 array."
    examples = [
        '=TB.OHLC("VNM") → [87000, 88000, 86500, 87500]',
    ]
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "array"
    output_columns = ["open", "high", "low", "close"]

    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        candle = await ctx.candle_at(ticker, tf, at)
        if candle is None:
            raise NoDataError(ticker, at, reason="no trading data")
        return [candle.open, candle.high, candle.low, candle.close]
