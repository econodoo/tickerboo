"""
Mock data seeder — generates realistic VN stock daily OHLCV data.

Used for development/testing when CafeF CDN is unreachable.
Real data replaces this once you run sync_full on your machine.

Usage:
    seeder = MockSeeder()
    result = await seeder.seed()
"""
from __future__ import annotations

import logging
import math
import random
from datetime import date, timedelta

from tickerboo.db.session import get_db

log = logging.getLogger(__name__)

# 15 popular VN tickers with realistic starting prices (VND) and volatility
MOCK_TICKERS = [
    ("VNM", "Vinamilk",              87000,  0.018, "HSX", "Consumer Staples"),
    ("VCB", "Vietcombank",            92000,  0.016, "HSX", "Banking"),
    ("FPT", "FPT Corporation",        130000, 0.022, "HSX", "Technology"),
    ("HPG", "Hoa Phat Group",         27000,  0.028, "HSX", "Materials"),
    ("MWG", "Mobile World",           55000,  0.025, "HSX", "Retail"),
    ("VHM", "Vinhomes",               42000,  0.024, "HSX", "Real Estate"),
    ("MSN", "Masan Group",            75000,  0.020, "HSX", "Conglomerate"),
    ("TCB", "Techcombank",            35000,  0.021, "HSX", "Banking"),
    ("ACB", "Asia Commercial Bank",   25000,  0.019, "HNX", "Banking"),
    ("VPB", "VPBank",                 20000,  0.023, "HSX", "Banking"),
    ("HSG", "Hoa Sen Group",          18000,  0.032, "HSX", "Materials"),
    ("SSI", "SSI Securities",         30000,  0.026, "HSX", "Financial Services"),
    ("VIC", "Vingroup",               40000,  0.021, "HSX", "Conglomerate"),
    ("NVL", "Novaland",               15000,  0.035, "HSX", "Real Estate"),
    ("GAS", "PV Gas",                 78000,  0.017, "HSX", "Energy"),
]

TRADING_DAYS = 500  # ~2 years of daily data


def _generate_ticker(
    symbol: str, start_price: float, volatility: float, n_days: int = TRADING_DAYS
) -> list[dict]:
    """Generate realistic daily OHLCV using geometric Brownian motion."""
    rng = random.Random(hash(symbol) % 2**32)

    records = []
    price = start_price
    base_date = date(2024, 1, 2)  # start from Jan 2 2024
    day_idx = 0

    for i in range(int(n_days * 1.45)):  # extra to account for weekends
        d = base_date + timedelta(days=i)
        if d.weekday() >= 5:  # skip weekends
            continue
        if day_idx >= n_days:
            break

        # Random return with slight positive drift
        ret = rng.gauss(0.0002, volatility)
        price = price * (1 + ret)

        # Intraday range
        daily_spread = price * volatility * 1.5
        open_p = price + rng.gauss(0, daily_spread * 0.3)
        high_p = max(open_p, price) + abs(rng.gauss(0, daily_spread * 0.4))
        low_p = min(open_p, price) - abs(rng.gauss(0, daily_spread * 0.4))

        # Ensure OHLC consistency
        high_p = max(high_p, open_p, price)
        low_p = min(low_p, open_p, price)

        # VN tick size: round to nearest 100 (for prices > 10000)
        tick = 100 if price > 10000 else 10
        close = round(price / tick) * tick
        open_p = round(open_p / tick) * tick
        high_p = round(high_p / tick) * tick
        low_p = round(low_p / tick) * tick

        # Volume: log-normal distribution, higher for liquid stocks
        base_vol = 14 + math.log(start_price / 10000)
        volume = max(1000, int(math.exp(rng.gauss(base_vol, 0.8))))

        records.append({
            "symbol": symbol,
            "date": d.isoformat(),
            "open": max(tick, open_p),
            "high": max(tick, high_p),
            "low": max(tick, low_p),
            "close": max(tick, close),
            "volume": volume,
        })
        day_idx += 1

    return records


class MockSeeder:
    """Seeds the DB with realistic mock data for development."""

    async def seed(self, clear_existing: bool = True) -> dict:
        """Generate and insert mock data for all tickers."""
        db = await get_db()

        if clear_existing:
            await db.execute("DELETE FROM daily_ohlcv WHERE source='mock'")
            await db.commit()

        total = 0
        for symbol, name, price, vol, exchange, industry in MOCK_TICKERS:
            records = _generate_ticker(symbol, price, vol)
            await db.executemany(
                """INSERT OR REPLACE INTO daily_ohlcv
                   (symbol, date, open, high, low, close, volume, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'mock')""",
                [(r["symbol"], r["date"], r["open"], r["high"],
                  r["low"], r["close"], r["volume"]) for r in records],
            )
            # Update stocks table
            await db.execute(
                """INSERT OR REPLACE INTO stocks
                   (symbol, name, exchange, industry, first_date, last_date, total_bars, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (symbol, name, exchange, industry,
                 records[0]["date"], records[-1]["date"], len(records)),
            )
            total += len(records)

        await db.commit()
        log.info("Mock seed complete: %d records for %d tickers", total, len(MOCK_TICKERS))
        return {"tickers": len(MOCK_TICKERS), "records": total, "source": "mock"}
