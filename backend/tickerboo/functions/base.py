"""
Base classes for TickerBoo function plugins.

Every function (TB.RSI, TB.PRICE, TB.CANDLES, etc.) inherits FunctionPlugin
and lives in its own file under tickerboo/functions/<category>/.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


@dataclass
class Param:
    """Declares one parameter of a function plugin."""
    name: str
    type: Literal["string", "number", "integer", "date", "boolean"] = "string"
    required: bool = False
    default: Any = None
    choices: list | None = None
    min: float | None = None
    max: float | None = None
    desc: str = ""

    def validate(self, value: Any) -> Any:
        """Validate and coerce a raw value. Raises ValueError on failure."""
        if value is None:
            if self.required:
                raise ValueError(f"Parameter '{self.name}' is required")
            return self.default

        # Type coercion
        if self.type == "number":
            value = float(value)
        elif self.type == "integer":
            value = int(value)
        elif self.type == "boolean":
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
            value = bool(value)
        elif self.type == "date":
            from tickerboo.utils.dates import parse_at
            value = parse_at(value)
        elif self.type == "string":
            value = str(value).strip()

        # Constraints
        if self.choices and value not in self.choices:
            raise ValueError(
                f"'{self.name}' must be one of {self.choices}, got '{value}'"
            )
        if self.min is not None and isinstance(value, (int, float)) and value < self.min:
            raise ValueError(f"'{self.name}' must be >= {self.min}, got {value}")
        if self.max is not None and isinstance(value, (int, float)) and value > self.max:
            raise ValueError(f"'{self.name}' must be <= {self.max}, got {value}")

        return value

    def to_dict(self) -> dict:
        d = {"name": self.name, "type": self.type, "required": self.required}
        if self.default is not None:
            d["default"] = self.default
        if self.choices:
            d["choices"] = self.choices
        if self.desc:
            d["description"] = self.desc
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        return d


# Available timeframes (EoD first, intraday later)
TIMEFRAMES_EOD = ("1d", "1w")
TIMEFRAMES_INTRADAY = ("15m", "1h")     # Phase B
TIMEFRAMES_ALL = TIMEFRAMES_EOD + TIMEFRAMES_INTRADAY


# Reusable param presets for ticker/tf/at (most functions share these)
PARAM_TICKER = Param("ticker", "string", required=True, desc="Ticker symbol e.g. VNM, VCB")
PARAM_TF     = Param("tf", "string", default="1d", choices=list(TIMEFRAMES_ALL),
                      desc="Timeframe: 15m, 1h, 1d, 1w (EoD only for now: 1d, 1w)")
PARAM_AT     = Param("at", "date", default=None,
                      desc="Date/datetime (ISO or Excel serial). Default = latest available bar.")
PARAM_N      = Param("n", "integer", default=100, min=1, max=5000,
                      desc="Number of bars to return")


class FunctionPlugin:
    """
    Base class for all TB.* function plugins.

    Subclass this, set the class-level attributes, implement compute(),
    then decorate with @register. That's it — the function is live.
    """
    # ── Identity ─────────────────────────────────────────────────────────
    name: str = ""                          # "RSI" → exposed as TB.RSI
    category: str = "general"               # price, momentum, volatility, ...
    tier: str = "simple"                    # simple | advanced | experimental
    description: str = ""
    examples: list[str] = []

    # ── Schema ────────────────────────────────────────────────────────────
    params: list[Param] = []
    output: str = "scalar"                  # scalar | array | object | text | url
    output_columns: list[str] | None = None # for array output, e.g. ["upper","middle","lower"]

    # ── Performance ───────────────────────────────────────────────────────
    cacheable: bool = True
    lookback_bars: int = 1                  # bars needed for warm-up

    # ── The work ──────────────────────────────────────────────────────────
    async def compute(self, ctx, **kwargs) -> Any:
        """
        Compute the function result.

        Args:
            ctx: ComputeContext — provides candles(), call(), db access
            **kwargs: validated parameter values (ticker, tf, period, at, etc.)

        Returns:
            Scalar (float/int/str), list (1D array), list[list] (2D), or dict.
        """
        raise NotImplementedError(f"{self.name}.compute() not implemented")

    def validate_params(self, raw: dict) -> dict:
        """Validate and coerce raw params dict against self.params."""
        result = {}
        for p in self.params:
            value = raw.get(p.name)
            result[p.name] = p.validate(value)
        return result

    def to_dict(self) -> dict:
        """Serialize function metadata for /functions endpoint."""
        return {
            "name": self.name,
            "category": self.category,
            "tier": self.tier,
            "description": self.description,
            "examples": self.examples,
            "params": [p.to_dict() for p in self.params],
            "output": self.output,
            "output_columns": self.output_columns,
            "formula": f'=TB.{self.name}({", ".join(p.name for p in self.params)})',
        }
