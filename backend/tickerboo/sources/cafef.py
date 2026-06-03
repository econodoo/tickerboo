"""
CafeF data source — downloads historical EOD candles from CafeF CDN.

Two download modes:
  - 'upto': Full history ZIP (all tickers, all dates up to target)
  - 'daily': Single-day ZIP (one day, all tickers)

Data is adjusted (dividends/splits already factored in).
AmiBroker CSV format inside ZIP: SYMBOL,YYYYMMDD,OPEN,HIGH,LOW,CLOSE,VOLUME

Usage:
    cafef = CafeF()
    result = await cafef.sync_full()       # initial backfill
    result = await cafef.sync_catchup()    # daily catch-up
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from tickerboo.config import settings
from tickerboo.db.session import get_db, fetch_one, fetch_all

log = logging.getLogger(__name__)

CDN_PREFIX = "https://cafef1.mediacdn.vn/data/ami_data/"


class CafeF:
    """CafeF EOD data downloader and parser."""

    def __init__(self):
        self.client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=120.0,
                follow_redirects=True,
                headers={"User-Agent": "TickerBoo/1.0"},
            )
        return self.client

    # ── URL construction ─────────────────────────────────────────────────

    @staticmethod
    def _build_url(target_date: date, download_type: str = "upto") -> str:
        """Build CafeF CDN URL for adjusted data."""
        folder = target_date.strftime("%Y%m%d")
        date_file = target_date.strftime("%d%m%Y")
        upto = "Upto" if download_type == "upto" else ""
        filename = f"CafeF.SolieuGD.{upto}{date_file}.zip"
        return f"{CDN_PREFIX}{folder}/{filename}"

    # ── Download ─────────────────────────────────────────────────────────

    async def download_zip(
        self, target_date: date, download_type: str = "upto", retries: int = 7
    ) -> Optional[bytes]:
        """
        Download a CafeF ZIP, trying target_date then going backwards.

        CafeF doesn't publish on weekends/holidays, so we try up to
        `retries` previous days to find the latest available file.
        """
        client = await self._get_client()

        for days_back in range(retries + 1):
            d = target_date - timedelta(days=days_back)
            url = self._build_url(d, download_type)

            try:
                log.info("CafeF download: %s", url)
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    log.info(
                        "CafeF download OK: %s (%d KB)",
                        d.isoformat(), len(resp.content) // 1024,
                    )
                    return resp.content
                else:
                    log.debug("CafeF %s: HTTP %d (size %d)", d, resp.status_code, len(resp.content))
            except httpx.HTTPError as e:
                log.warning("CafeF download error for %s: %s", d, e)

        log.error("CafeF: no data found after %d retries from %s", retries, target_date)
        return None

    # ── Parse ────────────────────────────────────────────────────────────

    @staticmethod
    def parse_zip(zip_bytes: bytes) -> list[dict]:
        """
        Parse CafeF AmiBroker ZIP into list of candle dicts.

        Format per line: SYMBOL,YYYYMMDD,OPEN,HIGH,LOW,CLOSE,VOLUME
        May also have header lines starting with '<' which we skip.
        """
        records = []
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    with zf.open(name) as f:
                        for raw_line in f:
                            line = raw_line.decode("utf-8", errors="ignore").strip()
                            if not line or line.startswith("<") or line.startswith("!"):
                                continue
                            parts = line.split(",")
                            if len(parts) < 7:
                                continue
                            try:
                                symbol = parts[0].strip().upper()
                                date_str = parts[1].strip()
                                if len(date_str) != 8:
                                    continue
                                iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

                                records.append({
                                    "symbol": symbol,
                                    "date": iso_date,
                                    "open": float(parts[2]),
                                    "high": float(parts[3]),
                                    "low": float(parts[4]),
                                    "close": float(parts[5]),
                                    "volume": int(float(parts[6])),
                                })
                            except (ValueError, IndexError):
                                continue
        except zipfile.BadZipFile:
            log.error("CafeF: invalid ZIP file")
            return []

        log.info("CafeF parsed %d records from ZIP", len(records))
        return records

    # ── Upsert to DB ─────────────────────────────────────────────────────

    async def upsert_records(self, records: list[dict]) -> dict:
        """Insert or replace candle records into daily_ohlcv."""
        if not records:
            return {"inserted": 0, "tickers": 0}

        db = await get_db()

        await db.executemany(
            """INSERT OR REPLACE INTO daily_ohlcv
               (symbol, date, open, high, low, close, volume, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'cafef')""",
            [
                (r["symbol"], r["date"], r["open"], r["high"],
                 r["low"], r["close"], r["volume"])
                for r in records
            ],
        )
        await db.commit()

        # Update stocks table
        tickers = set(r["symbol"] for r in records)
        for t in tickers:
            await db.execute(
                """INSERT INTO stocks (symbol, first_date, last_date, total_bars, updated_at)
                   VALUES (?, 
                     (SELECT MIN(date) FROM daily_ohlcv WHERE symbol=?),
                     (SELECT MAX(date) FROM daily_ohlcv WHERE symbol=?),
                     (SELECT COUNT(*) FROM daily_ohlcv WHERE symbol=?),
                     datetime('now'))
                   ON CONFLICT(symbol) DO UPDATE SET
                     last_date = excluded.last_date,
                     total_bars = excluded.total_bars,
                     updated_at = excluded.updated_at""",
                (t, t, t, t),
            )
        await db.commit()

        log.info("Upserted %d records for %d tickers", len(records), len(tickers))
        return {"inserted": len(records), "tickers": len(tickers)}

    # ── Sync operations ──────────────────────────────────────────────────

    async def get_last_date(self) -> date | None:
        """Get the most recent date across all tickers in daily_ohlcv."""
        row = await fetch_one("SELECT MAX(date) as max_date FROM daily_ohlcv")
        if row and row["max_date"]:
            return date.fromisoformat(row["max_date"])
        return None

    async def sync_full(self) -> dict:
        """
        Full historical sync — downloads the 'upto' ZIP and ingests everything.

        This is a one-time operation for initial backfill.
        """
        log.info("CafeF full sync starting...")
        db = await get_db()

        # Log sync start
        await db.execute(
            "INSERT INTO data_sync (sync_type, source, started_at, status) VALUES ('full', 'cafef', datetime('now'), 'running')"
        )
        await db.commit()

        try:
            zip_bytes = await self.download_zip(date.today(), "upto")
            if not zip_bytes:
                await self._finish_sync("full", "failed", error="Could not download CafeF ZIP")
                return {"error": "download failed"}

            records = self.parse_zip(zip_bytes)
            result = await self.upsert_records(records)
            await self._finish_sync("full", "completed", records=result["inserted"], tickers=result["tickers"])

            log.info("CafeF full sync complete: %d records, %d tickers", result["inserted"], result["tickers"])
            return result

        except Exception as e:
            log.exception("CafeF full sync failed")
            await self._finish_sync("full", "failed", error=str(e))
            return {"error": str(e)}

    async def sync_catchup(self) -> dict:
        """
        Catchup sync — downloads individual daily files for missing days.

        Runs after initial backfill to fill gaps.
        """
        last = await self.get_last_date()
        if not last:
            log.info("No existing data — falling back to full sync")
            return await self.sync_full()

        today = date.today()
        if last >= today:
            log.info("Already up to date (last: %s)", last)
            return {"status": "up_to_date", "last_date": last.isoformat()}

        log.info("CafeF catchup: %s → %s", last, today)
        db = await get_db()
        await db.execute(
            "INSERT INTO data_sync (sync_type, source, started_at, status) VALUES ('catchup', 'cafef', datetime('now'), 'running')"
        )
        await db.commit()

        total_records = 0
        days_with_data = 0
        current = last + timedelta(days=1)

        while current <= today:
            # Skip weekends (CafeF won't have data)
            if current.weekday() < 5:  # Mon-Fri
                zip_bytes = await self.download_zip(current, "daily", retries=0)
                if zip_bytes:
                    records = self.parse_zip(zip_bytes)
                    if records:
                        await self.upsert_records(records)
                        total_records += len(records)
                        days_with_data += 1
            current += timedelta(days=1)

        await self._finish_sync("catchup", "completed", records=total_records, tickers=days_with_data)

        log.info("CafeF catchup done: %d records over %d days", total_records, days_with_data)
        return {
            "days_synced": (today - last).days,
            "days_with_data": days_with_data,
            "records": total_records,
        }

    async def get_sync_status(self) -> dict:
        """Get the most recent sync log entry."""
        row = await fetch_one(
            "SELECT * FROM data_sync WHERE source='cafef' ORDER BY id DESC LIMIT 1"
        )
        if not row:
            return {"status": "never_synced"}
        return dict(row)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _finish_sync(self, sync_type: str, status: str, records: int = 0,
                           tickers: int = 0, error: str = None):
        db = await get_db()
        await db.execute(
            """UPDATE data_sync
               SET status=?, completed_at=datetime('now'), records_count=?, tickers_count=?, error_message=?
               WHERE id = (SELECT MAX(id) FROM data_sync WHERE sync_type=? AND source='cafef')""",
            (status, records, tickers, error, sync_type),
        )
        await db.commit()

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None
