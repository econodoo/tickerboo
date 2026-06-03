"""TB.PRICE — latest closing price for a ticker."""
from tickerboo.functions.base import FunctionPlugin, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.utils.errors import NoDataError


@register
class Price(FunctionPlugin):
    name = "PRICE"
    category = "price"
    tier = "simple"
    description = "Latest closing price. Alias for TB.CLOSE."
    examples = [
        '=TB.PRICE("VNM")                → 87500',
        '=TB.PRICE("VNM", "1d", "2024-06-15") → 86000',
        '=TB.PRICE("VNM", "1w")          → 87500 (latest weekly close)',
    ]
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        candle = await ctx.candle_at(ticker, tf, at)
        if candle is None:
            raise NoDataError(ticker, at, reason="no trading data")
        return candle.close
