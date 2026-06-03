"""
TB.OPEN, TB.HIGH, TB.LOW, TB.CLOSE, TB.VOL

Individual OHLCV components. All follow the same pattern:
fetch candle → return one field. Generated via factory to stay DRY.
"""
from tickerboo.functions.base import FunctionPlugin, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.utils.errors import NoDataError


def _make_component(field: str, label: str, desc: str):
    """Generate a FunctionPlugin class for one OHLCV component."""

    class _Plugin(FunctionPlugin):
        name = field.upper() if field != "volume" else "VOL"
        category = "price"
        tier = "simple"
        description = desc
        examples = [
            f'=TB.{field.upper() if field != "volume" else "VOL"}("VNM") → {label} for latest bar',
            f'=TB.{field.upper() if field != "volume" else "VOL"}("VNM", "1d", "2024-06-15") → at specific date',
        ]
        params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
        output = "scalar"

        async def compute(self, ctx, *, ticker, tf="1d", at=None):
            candle = await ctx.candle_at(ticker, tf, at)
            if candle is None:
                raise NoDataError(ticker, at, reason="no trading data")
            return getattr(candle, field)

    _Plugin.__name__ = field.upper()
    _Plugin.__qualname__ = field.upper()
    return _Plugin


# Register all five components
Open  = register(_make_component("open",   "Open price",   "Opening price of the bar"))
High  = register(_make_component("high",   "High price",   "Highest price during the bar"))
Low   = register(_make_component("low",    "Low price",    "Lowest price during the bar"))
Close = register(_make_component("close",  "Close price",  "Closing price of the bar"))
Vol   = register(_make_component("volume", "Volume",       "Trading volume of the bar"))
