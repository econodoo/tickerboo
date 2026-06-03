"""TB.RSI — Relative Strength Index (0-100 momentum oscillator)."""
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last


@register
class RSI(FunctionPlugin):
    name = "RSI"
    category = "momentum"
    tier = "simple"
    description = "Relative Strength Index — momentum oscillator (0-100). >70 overbought, <30 oversold."
    examples = [
        '=TB.RSI("VNM")              → 62.4 (default: 14-period daily)',
        '=TB.RSI("VNM", "1d", 21)    → 58.1',
    ]
    params = [
        PARAM_TICKER, PARAM_TF,
        Param("period", "integer", default=14, min=2, max=200, desc="Lookback period (default 14)"),
        PARAM_AT,
    ]
    output = "scalar"
    lookback_bars = 60

    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, max(period * 3, 50))
        return safe_last(talib.RSI(d["close"], timeperiod=period))
