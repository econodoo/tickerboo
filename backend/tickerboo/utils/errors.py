"""
TickerBoo error types.

Plugins raise these; the API dispatcher catches and formats responses.
"""


class TickerBooError(Exception):
    """Base class for all TickerBoo errors."""
    code: str = "error"
    status_code: int = 400

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict:
        d = {"status": "error", "code": self.code, "message": self.message}
        d.update(self.extra)
        return d


class NoDataError(TickerBooError):
    """No trading data exists for the requested ticker/date."""
    code = "no_data"
    status_code = 200  # not a server error — just empty result

    def __init__(self, ticker: str, at=None, reason: str = "no data available", nearest=None):
        msg = f"No data for {ticker}"
        if at:
            msg += f" at {at}"
        msg += f": {reason}"
        super().__init__(msg, ticker=ticker, reason=reason)
        if nearest:
            self.extra["nearest"] = str(nearest)


class TickerNotFoundError(TickerBooError):
    """Ticker symbol does not exist in our universe."""
    code = "ticker_not_found"
    status_code = 200


class InvalidParamError(TickerBooError):
    """Invalid parameter value."""
    code = "invalid_param"
    status_code = 400


class InsufficientDataError(TickerBooError):
    """Not enough historical data to compute indicator."""
    code = "insufficient_data"
    status_code = 200

    def __init__(self, ticker: str, needed: int, available: int):
        super().__init__(
            f"{ticker}: need {needed} bars but only {available} available",
            needed=needed, available=available,
        )


class TimeframeNotAvailable(TickerBooError):
    """Requested timeframe not yet implemented."""
    code = "timeframe_not_available"
    status_code = 501  # Not Implemented

    def __init__(self, tf: str):
        super().__init__(
            f"Timeframe '{tf}' not available yet. EoD only: 1d, 1w",
            timeframe=tf,
        )


class FunctionNotFoundError(TickerBooError):
    """Function name not in registry."""
    code = "function_not_found"
    status_code = 404
