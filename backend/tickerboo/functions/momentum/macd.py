"""TB.MACD — Moving Average Convergence Divergence + individual components."""
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last

_FAST   = Param("fast",   "integer", default=12, min=2, max=200, desc="Fast EMA period")
_SLOW   = Param("slow",   "integer", default=26, min=2, max=200, desc="Slow EMA period")
_SIGNAL = Param("signal", "integer", default=9,  min=2, max=200, desc="Signal EMA period")


async def _compute_macd(ctx, ticker, tf, fast, slow, signal, at):
    """Shared MACD computation for all sub-components."""
    d = await get_ohlcv_arrays(ctx, ticker, tf, at, max(slow * 3, 80))
    macd, sig, hist = talib.MACD(d["close"], fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return safe_last(macd), safe_last(sig), safe_last(hist)


@register
class MACD(FunctionPlugin):
    name = "MACD"
    category = "momentum"
    tier = "simple"
    description = "MACD — returns [MACD line, Signal line, Histogram] as 1×3 array."
    examples = ['=TB.MACD("VNM") → [320.5, 280.1, 40.4]']
    params = [PARAM_TICKER, PARAM_TF, _FAST, _SLOW, _SIGNAL, PARAM_AT]
    output = "array"
    output_columns = ["macd", "signal", "histogram"]

    async def compute(self, ctx, *, ticker, tf="1d", fast=12, slow=26, signal=9, at=None):
        m, s, h = await _compute_macd(ctx, ticker, tf, fast, slow, signal, at)
        return [m, s, h]


@register
class MACD_LINE(FunctionPlugin):
    name = "MACD_LINE"
    category = "momentum"
    tier = "simple"
    description = "MACD line (fast EMA − slow EMA)."
    params = [PARAM_TICKER, PARAM_TF, _FAST, _SLOW, _SIGNAL, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", fast=12, slow=26, signal=9, at=None):
        m, _, _ = await _compute_macd(ctx, ticker, tf, fast, slow, signal, at)
        return m


@register
class MACD_SIGNAL(FunctionPlugin):
    name = "MACD_SIGNAL"
    category = "momentum"
    tier = "simple"
    description = "MACD signal line (EMA of MACD line)."
    params = [PARAM_TICKER, PARAM_TF, _FAST, _SLOW, _SIGNAL, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", fast=12, slow=26, signal=9, at=None):
        _, s, _ = await _compute_macd(ctx, ticker, tf, fast, slow, signal, at)
        return s


@register
class MACD_HIST(FunctionPlugin):
    name = "MACD_HIST"
    category = "momentum"
    tier = "simple"
    description = "MACD histogram (MACD line − Signal line)."
    params = [PARAM_TICKER, PARAM_TF, _FAST, _SLOW, _SIGNAL, PARAM_AT]
    output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", fast=12, slow=26, signal=9, at=None):
        _, _, h = await _compute_macd(ctx, ticker, tf, fast, slow, signal, at)
        return h
