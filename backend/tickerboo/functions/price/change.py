"""
Price change functions — the first thing traders look at.

TB.CHANGE("VNM")           → absolute change (close - prev_close)
TB.CHANGE_PCT("VNM")       → percentage change
TB.HIGH52W("VNM")          → 52-week high
TB.LOW52W("VNM")           → 52-week low
TB.FROM_HIGH52W("VNM")     → % below 52-week high (drawdown)
TB.FROM_LOW52W("VNM")      → % above 52-week low
"""
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays
from tickerboo.utils.errors import NoDataError, InsufficientDataError


@register
class Change(FunctionPlugin):
    name = "CHANGE"
    category = "price"
    tier = "simple"
    description = "Absolute price change (close − previous close)."
    examples = ['=TB.CHANGE("VNM") → 500 (price rose ₫500)']
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        candles = await ctx.candles(ticker, tf, n=2, ending_at=at)
        if len(candles) < 2:
            raise InsufficientDataError(ticker, 2, len(candles))
        return round(candles[-1].close - candles[-2].close, 2)


@register
class ChangePct(FunctionPlugin):
    name = "CHANGE_PCT"
    category = "price"
    tier = "simple"
    description = "Percentage price change from previous bar. Returns %."
    examples = ['=TB.CHANGE_PCT("VNM") → 0.58 (means +0.58%)']
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        candles = await ctx.candles(ticker, tf, n=2, ending_at=at)
        if len(candles) < 2:
            raise InsufficientDataError(ticker, 2, len(candles))
        prev = candles[-2].close
        if prev == 0:
            return 0
        return round((candles[-1].close - prev) / prev * 100, 4)


@register
class High52W(FunctionPlugin):
    name = "HIGH52W"
    category = "price"
    tier = "simple"
    description = "52-week (260 trading days) high price."
    examples = ['=TB.HIGH52W("VNM") → 128700']
    params = [PARAM_TICKER, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, at=None):
        candles = await ctx.candles(ticker, "1d", n=260, ending_at=at)
        if not candles:
            raise NoDataError(ticker, at)
        return max(c.high for c in candles)


@register
class Low52W(FunctionPlugin):
    name = "LOW52W"
    category = "price"
    tier = "simple"
    description = "52-week (260 trading days) low price."
    examples = ['=TB.LOW52W("VNM") → 78200']
    params = [PARAM_TICKER, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, at=None):
        candles = await ctx.candles(ticker, "1d", n=260, ending_at=at)
        if not candles:
            raise NoDataError(ticker, at)
        return min(c.low for c in candles)


@register
class FromHigh52W(FunctionPlugin):
    name = "FROM_HIGH52W"
    category = "price"
    tier = "simple"
    description = "Percentage below 52-week high (drawdown). 0 = at high, -15 = 15% below."
    examples = ['=TB.FROM_HIGH52W("VNM") → -12.5']
    params = [PARAM_TICKER, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, at=None):
        candles = await ctx.candles(ticker, "1d", n=260, ending_at=at)
        if not candles:
            raise NoDataError(ticker, at)
        high = max(c.high for c in candles)
        curr = candles[-1].close
        if high == 0:
            return 0
        return round((curr - high) / high * 100, 2)


@register
class FromLow52W(FunctionPlugin):
    name = "FROM_LOW52W"
    category = "price"
    tier = "simple"
    description = "Percentage above 52-week low. 0 = at low, +50 = 50% above."
    examples = ['=TB.FROM_LOW52W("VNM") → 35.2']
    params = [PARAM_TICKER, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, at=None):
        candles = await ctx.candles(ticker, "1d", n=260, ending_at=at)
        if not candles:
            raise NoDataError(ticker, at)
        low = min(c.low for c in candles)
        curr = candles[-1].close
        if low == 0:
            return 0
        return round((curr - low) / low * 100, 2)
