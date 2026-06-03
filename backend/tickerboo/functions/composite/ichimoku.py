"""
Ichimoku Cloud — custom implementation (not in TA-Lib).

Components:
  Tenkan-sen (conversion):  (highest high + lowest low) / 2 over 9 periods
  Kijun-sen  (base line):   (highest high + lowest low) / 2 over 26 periods
  Senkou Span A (leading):  (tenkan + kijun) / 2, plotted 26 ahead → current value
  Senkou Span B (leading):  midline of 52 periods, plotted 26 ahead → current value
  Chikou Span (lagging):    close plotted 26 back → current bar = close[−26]
"""
import numpy as np
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays


def _donchian_mid(high: np.ndarray, low: np.ndarray, period: int) -> np.ndarray:
    """Rolling (max(high) + min(low)) / 2 over `period` bars."""
    n = len(high)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        h = np.max(high[i - period + 1:i + 1])
        l = np.min(low[i - period + 1:i + 1])
        result[i] = (h + l) / 2
    return result


async def _compute_ichimoku(ctx, ticker, tf, tenkan_p, kijun_p, senkou_p, at):
    """Compute all 5 Ichimoku components."""
    lookback = max(senkou_p + kijun_p, 100)
    d = await get_ohlcv_arrays(ctx, ticker, tf, at, lookback)

    tenkan = _donchian_mid(d["high"], d["low"], tenkan_p)
    kijun  = _donchian_mid(d["high"], d["low"], kijun_p)

    # Senkou A & B: normally plotted 26 periods ahead.
    # "Current" value = what was computed 26 bars ago and is now visible.
    senkou_a_raw = (tenkan + kijun) / 2
    senkou_b_raw = _donchian_mid(d["high"], d["low"], senkou_p)

    # The "current" cloud values = shift back by kijun_p bars
    idx = len(d["close"]) - 1
    shift = kijun_p
    sa = float(senkou_a_raw[idx - shift]) if (idx - shift) >= 0 and not np.isnan(senkou_a_raw[idx - shift]) else None
    sb = float(senkou_b_raw[idx - shift]) if (idx - shift) >= 0 and not np.isnan(senkou_b_raw[idx - shift]) else None

    t_val = float(tenkan[idx]) if not np.isnan(tenkan[idx]) else None
    k_val = float(kijun[idx])  if not np.isnan(kijun[idx])  else None

    # Chikou = current close value (which is plotted 26 bars back on chart)
    chi = float(d["close"][idx])

    return (
        round(t_val, 2) if t_val else None,
        round(k_val, 2) if k_val else None,
        round(sa, 2) if sa else None,
        round(sb, 2) if sb else None,
        round(chi, 2),
    )


_TENKAN_P = Param("tenkan_period", "integer", default=9,  min=2, desc="Tenkan-sen period")
_KIJUN_P  = Param("kijun_period",  "integer", default=26, min=2, desc="Kijun-sen period")
_SENKOU_P = Param("senkou_period", "integer", default=52, min=2, desc="Senkou Span B period")


@register
class ICHIMOKU(FunctionPlugin):
    name = "ICHIMOKU"
    category = "composite"
    tier = "simple"
    description = "Ichimoku Cloud — returns [Tenkan, Kijun, Senkou A, Senkou B, Chikou]."
    examples = ['=TB.ICHIMOKU("VNM") → [87000, 86500, 86800, 86200, 87500]']
    params = [PARAM_TICKER, PARAM_TF, _TENKAN_P, _KIJUN_P, _SENKOU_P, PARAM_AT]
    output = "array"
    output_columns = ["tenkan", "kijun", "senkou_a", "senkou_b", "chikou"]

    async def compute(self, ctx, *, ticker, tf="1d", tenkan_period=9, kijun_period=26, senkou_period=52, at=None):
        return list(await _compute_ichimoku(ctx, ticker, tf, tenkan_period, kijun_period, senkou_period, at))


@register
class TENKAN(FunctionPlugin):
    name = "TENKAN"
    category = "composite"
    tier = "simple"
    description = "Tenkan-sen (conversion line) — midline of 9-period high/low."
    params = [PARAM_TICKER, PARAM_TF, Param("period","integer",default=9,min=2), PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=9, at=None):
        t, *_ = await _compute_ichimoku(ctx, ticker, tf, period, 26, 52, at)
        return t


@register
class KIJUN(FunctionPlugin):
    name = "KIJUN"
    category = "composite"
    tier = "simple"
    description = "Kijun-sen (base line) — midline of 26-period high/low."
    params = [PARAM_TICKER, PARAM_TF, Param("period","integer",default=26,min=2), PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=26, at=None):
        _, k, *_ = await _compute_ichimoku(ctx, ticker, tf, 9, period, 52, at)
        return k


@register
class SENKOU_A(FunctionPlugin):
    name = "SENKOU_A"
    category = "composite"
    tier = "advanced"
    description = "Senkou Span A (leading span A of the Ichimoku cloud)."
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        _, _, sa, *_ = await _compute_ichimoku(ctx, ticker, tf, 9, 26, 52, at)
        return sa


@register
class SENKOU_B(FunctionPlugin):
    name = "SENKOU_B"
    category = "composite"
    tier = "advanced"
    description = "Senkou Span B (leading span B of the Ichimoku cloud)."
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        *_, sb, _ = await _compute_ichimoku(ctx, ticker, tf, 9, 26, 52, at)
        return sb


@register
class CHIKOU(FunctionPlugin):
    name = "CHIKOU"
    category = "composite"
    tier = "advanced"
    description = "Chikou Span (lagging span — current close plotted 26 bars back)."
    params = [PARAM_TICKER, PARAM_TF, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", at=None):
        *_, chi = await _compute_ichimoku(ctx, ticker, tf, 9, 26, 52, at)
        return chi
