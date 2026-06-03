"""Momentum oscillators: STOCH, CCI, MFI, ADX, WILLR, ROC."""
import talib
from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_AT
from tickerboo.functions.registry import register
from tickerboo.functions.helpers import get_ohlcv_arrays, safe_last

_PER = Param("period", "integer", default=14, min=2, max=200, desc="Lookback period")


@register
class STOCH(FunctionPlugin):
    name = "STOCH"
    category = "momentum"
    tier = "simple"
    description = "Stochastic Oscillator — returns [%K, %D]."
    params = [PARAM_TICKER, PARAM_TF,
              Param("k", "integer", default=14, min=2, desc="K period"),
              Param("d", "integer", default=3, min=1, desc="D smoothing"),
              PARAM_AT]
    output = "array"
    output_columns = ["k", "d"]

    async def compute(self, ctx, *, ticker, tf="1d", k=14, d=3, at=None):
        arr = await get_ohlcv_arrays(ctx, ticker, tf, at, k * 3)
        sk, sd = talib.STOCH(arr["high"], arr["low"], arr["close"],
                             fastk_period=k, slowk_period=d, slowd_period=d)
        return [safe_last(sk), safe_last(sd)]


@register
class STOCH_K(FunctionPlugin):
    name = "STOCH_K"
    category = "momentum"
    tier = "simple"
    description = "Stochastic %K."
    params = [PARAM_TICKER, PARAM_TF, Param("k","integer",default=14), Param("d","integer",default=3), PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", k=14, d=3, at=None):
        arr = await get_ohlcv_arrays(ctx, ticker, tf, at, k * 3)
        sk, _ = talib.STOCH(arr["high"], arr["low"], arr["close"], fastk_period=k, slowk_period=d, slowd_period=d)
        return safe_last(sk)


@register
class STOCH_D(FunctionPlugin):
    name = "STOCH_D"
    category = "momentum"
    tier = "simple"
    description = "Stochastic %D."
    params = [PARAM_TICKER, PARAM_TF, Param("k","integer",default=14), Param("d","integer",default=3), PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", k=14, d=3, at=None):
        arr = await get_ohlcv_arrays(ctx, ticker, tf, at, k * 3)
        _, sd = talib.STOCH(arr["high"], arr["low"], arr["close"], fastk_period=k, slowk_period=d, slowd_period=d)
        return safe_last(sd)


@register
class CCI(FunctionPlugin):
    name = "CCI"
    category = "momentum"
    tier = "simple"
    description = "Commodity Channel Index — measures deviation from average price."
    params = [PARAM_TICKER, PARAM_TF, _PER, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 3)
        return safe_last(talib.CCI(d["high"], d["low"], d["close"], timeperiod=period))


@register
class MFI(FunctionPlugin):
    name = "MFI"
    category = "momentum"
    tier = "simple"
    description = "Money Flow Index — volume-weighted RSI (0-100)."
    params = [PARAM_TICKER, PARAM_TF, _PER, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 3)
        return safe_last(talib.MFI(d["high"], d["low"], d["close"], d["volume"], timeperiod=period))


@register
class ADX(FunctionPlugin):
    name = "ADX"
    category = "momentum"
    tier = "simple"
    description = "Average Directional Index — measures trend strength (0-100)."
    params = [PARAM_TICKER, PARAM_TF, _PER, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 4)
        return safe_last(talib.ADX(d["high"], d["low"], d["close"], timeperiod=period))


@register
class WILLR(FunctionPlugin):
    name = "WILLR"
    category = "momentum"
    tier = "advanced"
    description = "Williams %R — momentum (−100 to 0)."
    params = [PARAM_TICKER, PARAM_TF, _PER, PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=14, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period * 2)
        return safe_last(talib.WILLR(d["high"], d["low"], d["close"], timeperiod=period))


@register
class ROC(FunctionPlugin):
    name = "ROC"
    category = "momentum"
    tier = "advanced"
    description = "Rate of Change — percentage change over N periods."
    params = [PARAM_TICKER, PARAM_TF, Param("period","integer",default=10,min=1), PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=10, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period + 5)
        return safe_last(talib.ROC(d["close"], timeperiod=period))


@register
class MOM(FunctionPlugin):
    name = "MOM"
    category = "momentum"
    tier = "advanced"
    description = "Momentum — absolute difference over N periods."
    params = [PARAM_TICKER, PARAM_TF, Param("period","integer",default=10,min=1), PARAM_AT]
    output = "scalar"
    async def compute(self, ctx, *, ticker, tf="1d", period=10, at=None):
        d = await get_ohlcv_arrays(ctx, ticker, tf, at, period + 5)
        return safe_last(talib.MOM(d["close"], timeperiod=period))
