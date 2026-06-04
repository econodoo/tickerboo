"""
CafeF data source — downloads historical EOD candles from CafeF CDN.

v0.9: All sync operations route through IngestionEngine (turbo or patch mode).
      No more in-memory-parse-everything approach.

Usage:
    cafef = CafeF()
    result = await cafef.sync_full()       # saves ZIP → disk → turbo ingest
    result = await cafef.sync_catchup()    # daily files → patch ingest
"""
from __future__ import annotations

import asyncio
import io
import logging
import sqlite3
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx

from tickerboo.config import settings
from tickerboo.db.session import get_db, fetch_one, db_session

log = logging.getLogger(__name__)


def _get_url_prefix() -> str:
    """Get CafeF URL prefix — checks runtime config."""
    return getattr(settings, "cafef_url_prefix",
                   "https://cafef1.mediacdn.vn/data/ami_data/")


class CafeF:
    """CafeF EOD data downloader and parser."""

    def __init__(self):
        self.client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=120.0, follow_redirects=True,
                headers={"User-Agent": "TickerBoo/1.0"},
            )
        return self.client

    # ── URL construction ─────────────────────────────────────────────────

    @staticmethod
    def _build_url(target_date: date, download_type: str = "upto") -> str:
        prefix = _get_url_prefix()
        folder = target_date.strftime("%Y%m%d")
        date_file = target_date.strftime("%d%m%Y")
        upto = "Upto" if download_type == "upto" else ""
        filename = f"CafeF.SolieuGD.{upto}{date_file}.zip"
        return f"{prefix}{folder}/{filename}"

    # ── Download ─────────────────────────────────────────────────────────

    async def download_zip(
        self, target_date: date, download_type: str = "upto", retries: int = 7
    ) -> Optional[bytes]:
        """Download CafeF ZIP, trying backwards for weekends/holidays."""
        client = await self._get_client()

        for days_back in range(retries + 1):
            d = target_date - timedelta(days=days_back)
            url = self._build_url(d, download_type)
            try:
                log.info("CafeF download: %s", url)
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    log.info("CafeF OK: %s (%d KB)", d.isoformat(),
                             len(resp.content) // 1024)
                    return resp.content
                log.debug("CafeF %s: HTTP %d (%d bytes)",
                          d, resp.status_code, len(resp.content))
            except httpx.HTTPError as e:
                log.warning("CafeF error %s: %s", d, e)

        log.error("CafeF: no data after %d retries from %s", retries, target_date)
        return None

    # ── Sync: Full ───────────────────────────────────────────────────────

    async def sync_full(self) -> dict:
        """
        Full historical sync — download 'upto' ZIP, save to disk,
        ingest via IngestionEngine in turbo mode.
        """
        log.info("CafeF full sync starting...")
        db = await get_db()
        await db.execute(
            "INSERT INTO data_sync (sync_type, source, started_at, status) "
            "VALUES ('full', 'cafef', datetime('now'), 'running')"
        )
        await db.commit()

        try:
            zip_bytes = await self.download_zip(date.today(), "upto")
            if not zip_bytes:
                await self._finish_sync("full", "failed",
                                        error="Could not download CafeF ZIP")
                return {"error": "download failed"}

            # Save to disk (free memory immediately)
            uploads = Path(settings.db_path).parent / "uploads"
            uploads.mkdir(parents=True, exist_ok=True)
            dest = uploads / f"cafef_full_{date.today().strftime('%Y%m%d')}.zip"
            dest.write_bytes(zip_bytes)
            size_mb = len(zip_bytes) / 1024 / 1024
            del zip_bytes
            log.info("CafeF ZIP saved: %s (%.1f MB)", dest, size_mb)

            # Route through IngestionEngine (turbo mode)
            from tickerboo.sources.ingest import ingestion_engine
            job_id = await ingestion_engine.start_from_path(dest, "cafef", mode="full")

            # Wait for completion
            while ingestion_engine.is_busy:
                await asyncio.sleep(2)

            progress = ingestion_engine.get_progress(job_id)
            if progress and progress["status"] == "completed":
                result = {
                    "inserted": progress["records_inserted"],
                    "tickers": progress["tickers_found"],
                    "rate_rps": progress["rate_rps"],
                }
                await self._finish_sync("full", "completed",
                                        records=result["inserted"],
                                        tickers=result["tickers"])
                return result
            else:
                error = progress["error"] if progress else "Unknown"
                await self._finish_sync("full", "failed", error=error)
                return {"error": error}

        except Exception as e:
            log.exception("CafeF full sync failed")
            await self._finish_sync("full", "failed", error=str(e))
            return {"error": str(e)}

    # ── Sync: Catchup ────────────────────────────────────────────────────

    async def sync_catchup(self) -> dict:
        """
        Catchup sync — download daily files for missing days.
        Uses fast direct-insert for small daily files.
        """
        last = await self.get_last_date()
        if not last:
            log.info("No existing data — falling back to full sync")
            return await self.sync_full()

        today = date.today()
        if last >= today:
            return {"status": "up_to_date", "last_date": last.isoformat()}

        log.info("CafeF catchup: %s → %s", last, today)
        db = await get_db()
        await db.execute(
            "INSERT INTO data_sync (sync_type, source, started_at, status) "
            "VALUES ('catchup', 'cafef', datetime('now'), 'running')"
        )
        await db.commit()

        total_records = 0
        days_with_data = 0
        current = last + timedelta(days=1)

        while current <= today:
            if current.weekday() < 5:
                zip_bytes = await self.download_zip(current, "daily", retries=0)
                if zip_bytes:
                    inserted = self._fast_insert_small_zip(zip_bytes)
                    if inserted > 0:
                        total_records += inserted
                        days_with_data += 1
                    await asyncio.sleep(0)
            current += timedelta(days=1)

        # Update stocks metadata once at the end
        self._update_stocks_aggregate()

        await self._finish_sync("catchup", "completed",
                                records=total_records, tickers=days_with_data)
        log.info("CafeF catchup: %d records, %d days", total_records, days_with_data)
        return {
            "days_synced": (today - last).days,
            "days_with_data": days_with_data,
            "records": total_records,
        }

    def _fast_insert_small_zip(self, zip_bytes: bytes) -> int:
        """
        Fast insert for small daily ZIPs (~2K records).
        Uses raw sqlite3 + INSERT OR IGNORE in a single transaction.
        """
        records = []
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    with zf.open(name) as f:
                        for raw_line in f:
                            line = raw_line.decode("utf-8", errors="ignore").strip()
                            if not line or line[0] in ("<", "!"):
                                continue
                            parts = line.split(",")
                            if len(parts) < 7:
                                continue
                            try:
                                sym = parts[0].strip().upper()
                                ds = parts[1].strip()
                                if len(ds) != 8:
                                    continue
                                iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
                                records.append((
                                    sym, iso,
                                    float(parts[2]), float(parts[3]),
                                    float(parts[4]), float(parts[5]),
                                    int(float(parts[6])),
                                ))
                            except (ValueError, IndexError):
                                continue
        except zipfile.BadZipFile:
            return 0

        if not records:
            return 0

        conn = sqlite3.connect(str(settings.db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN TRANSACTION")
        conn.executemany(
            """INSERT OR IGNORE INTO daily_ohlcv
               (symbol, date, open, high, low, close, volume, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'cafef')""",
            records,
        )
        conn.execute("COMMIT")
        conn.close()
        return len(records)

    def _update_stocks_aggregate(self):
        """Bulk-update stocks table with single aggregate query."""
        conn = sqlite3.connect(str(settings.db_path), timeout=30)
        conn.execute("""
            INSERT OR REPLACE INTO stocks (symbol, first_date, last_date, total_bars, updated_at)
            SELECT symbol, MIN(date), MAX(date), COUNT(*), datetime('now')
            FROM daily_ohlcv GROUP BY symbol
        """)
        conn.commit()
        conn.close()

    # ── Status / helpers ─────────────────────────────────────────────────

    async def get_last_date(self) -> date | None:
        row = await fetch_one("SELECT MAX(date) as max_date FROM daily_ohlcv")
        if row and row["max_date"]:
            return date.fromisoformat(row["max_date"])
        return None

    async def get_sync_status(self) -> dict:
        row = await fetch_one(
            "SELECT * FROM data_sync WHERE source='cafef' ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else {"status": "never_synced"}

    async def _finish_sync(self, sync_type: str, status: str, records: int = 0,
                           tickers: int = 0, error: str = None):
        db = await get_db()
        await db.execute(
            """UPDATE data_sync
               SET status=?, completed_at=datetime('now'),
                   records_count=?, tickers_count=?, error_message=?
               WHERE id = (SELECT MAX(id) FROM data_sync
                           WHERE sync_type=? AND source='cafef')""",
            (status, records, tickers, error, sync_type),
        )
        await db.commit()

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None
