"""
Date / datetime utilities for TickerBoo.

All dates internal are Python date objects (EoD) or datetime objects (intraday).
DB stores ISO strings. API accepts ISO strings or Excel serial numbers.

VN trading session:
  HSX:  09:00 – 11:30, 13:00 – 15:00 (Mon-Fri, excl holidays)
  HNX:  09:00 – 11:30, 13:00 – 15:00
  UPCOM: 09:00 – 11:30, 13:00 – 15:00
  ATC: 14:30 – 14:45 (HSX) / 14:30 – 15:00 (HNX)
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

# Excel epoch: serial 1 = 1900-01-01 (with the Lotus 1-2-3 leap-year bug)
_EXCEL_EPOCH = datetime(1899, 12, 30)  # adjusts for the bug


def parse_at(value) -> date | datetime | None:
    """Parse the 'at' parameter from API/Excel.

    Accepts:
      None              → None (means "latest")
      "2024-06-15"      → date
      "2024-06-15T10:30" → datetime
      "2024-06-15 10:30" → datetime
      45458             → Excel serial (integer) → date
      45458.4375        → Excel serial (fraction) → datetime
      datetime/date obj → passed through

    Returns date for EoD, datetime for intraday, None for latest.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value

    # Numeric → Excel serial number
    if isinstance(value, (int, float)):
        return _excel_serial_to_date(value)

    # String parsing
    s = str(value).strip()
    if not s:
        return None

    # Try ISO date first (YYYY-MM-DD)
    if len(s) == 10 and s[4] == "-":
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass

    # Try ISO datetime (YYYY-MM-DDTHH:MM or YYYY-MM-DD HH:MM:SS etc)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    # Try DD/MM/YYYY (Vietnamese locale)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date/datetime: {value!r}")


def _excel_serial_to_date(serial: int | float) -> date | datetime:
    """Convert Excel serial number to Python date/datetime."""
    if isinstance(serial, float) and not serial.is_integer():
        # Has time component
        return _EXCEL_EPOCH + timedelta(days=serial)
    else:
        return (_EXCEL_EPOCH + timedelta(days=int(serial))).date()


def date_to_excel_serial(d: date | datetime) -> float:
    """Convert Python date/datetime to Excel serial number."""
    if isinstance(d, datetime):
        delta = d - _EXCEL_EPOCH
        return delta.days + delta.seconds / 86400
    return (d - _EXCEL_EPOCH.date()).days


def date_to_iso(d: date | datetime | None) -> str | None:
    """Convert to ISO string for DB storage / API response."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%dT%H:%M:%S")
    return d.isoformat()


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5=Sat, 6=Sun


def prev_weekday(d: date) -> date:
    """Return the most recent weekday <= d."""
    while is_weekend(d):
        d -= timedelta(days=1)
    return d


# VN public holidays (approximate — exact list changes yearly)
# This is a rough set; we'll refine by checking actual trading data
VN_HOLIDAYS_FIXED = {
    (1, 1),   # New Year
    (4, 30),  # Reunification
    (5, 1),   # Labour Day
    (9, 2),   # National Day
}
