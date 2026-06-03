"""
Shortcut functions — popular parameter presets baked in.

Each calls the underlying function via ctx.call(), so caching is shared.
No duplicate computation: TB.RSI14("VNM") hits the same cache as TB.RSI("VNM","1d",14).
"""
from tickerboo.functions.base import FunctionPlugin, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register


def _make_shortcut(name, target_fn, fixed_params, desc):
    """Generate a shortcut plugin class."""

    class _Short(FunctionPlugin):
        pass

    _Short.name = name
    _Short.category = "shortcut"
    _Short.tier = "simple"
    _Short.description = desc
    _Short.examples = [f'=TB.{name}("VNM") → calls TB.{target_fn} with {fixed_params}']
    _Short.params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    _Short.output = "scalar"

    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        return await ctx.call(target_fn, ticker=ticker, tf=tf, at=at, **fixed_params)

    _Short.compute = compute
    _Short.__name__ = name
    _Short.__qualname__ = name
    return _Short


# ── RSI shortcuts ────────────────────────────────────────────────────────────
register(_make_shortcut("RSI14", "RSI", {"period": 14}, "RSI with period 14 (most common)"))
register(_make_shortcut("RSI7",  "RSI", {"period": 7},  "RSI with period 7 (short-term)"))
register(_make_shortcut("RSI21", "RSI", {"period": 21}, "RSI with period 21"))

# ── SMA shortcuts ────────────────────────────────────────────────────────────
for n in (5, 10, 20, 50, 100, 200):
    register(_make_shortcut(f"MA{n}", "SMA", {"period": n}, f"Simple Moving Average {n}-period"))

# ── EMA shortcuts ────────────────────────────────────────────────────────────
for n in (12, 26, 50, 200):
    register(_make_shortcut(f"EMA{n}", "EMA", {"period": n}, f"Exponential Moving Average {n}-period"))

# ── MFI shortcuts ────────────────────────────────────────────────────────────
register(_make_shortcut("MFI14", "MFI", {"period": 14}, "Money Flow Index 14-period"))
