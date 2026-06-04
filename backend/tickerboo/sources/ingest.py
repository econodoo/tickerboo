"""
Async chunked data ingestion engine.

Reads ZIP/CSV files line-by-line, processes in 5K-record batches
to avoid OOM on large files (200MB+). All operations are non-blocking.

Usage:
    engine = IngestionEngine()
    job_id = await engine.start_file(file_id)
    status = engine.get_progress(job_id)
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from tickerboo.config import settings
from tickerboo.db.session import db_session, fetch_one, fetch_all, execute

log = logging.getLogger(__name__)

BATCH_SIZE = 5_000  # records per DB commit


@dataclass
class IngestionProgress:
    """Live progress for an in-flight ingestion job."""
    job_id: str
    file_id: int
    filename: str
    status: str = "pending"          # pending, parsing, ingesting, completed, failed
    phase: str = ""                  # "reading zip", "batch 3/42", etc.
    records_parsed: int = 0
    records_upserted: int = 0
    batches_done: int = 0
    batches_total: int = 0
    tickers_found: int = 0
    started_at: float = 0.0
    elapsed_sec: float = 0.0
    error: str = ""
    date_min: str = ""
    date_max: str = ""

    def to_dict(self) -> dict:
        self.elapsed_sec = round(time.time() - self.started_at, 1) if self.started_at else 0
        return {
            "job_id": self.job_id,
            "file_id": self.file_id,
            "filename": self.filename,
            "status": self.status,
            "phase": self.phase,
            "records_parsed": self.records_parsed,
            "records_upserted": self.records_upserted,
            "batches_done": self.batches_done,
            "batches_total": self.batches_total,
            "tickers_found": self.tickers_found,
            "elapsed_sec": self.elapsed_sec,
            "error": self.error,
            "date_min": self.date_min,
            "date_max": self.date_max,
        }


class IngestionEngine:
    """Manages async, chunked ingestion from ZIP/CSV files."""

    def __init__(self):
        self._jobs: dict[str, IngestionProgress] = {}
        self._active_job: str | None = None

    @property
    def is_busy(self) -> bool:
        return self._active_job is not None

    def get_progress(self, job_id: str) -> dict | None:
        p = self._jobs.get(job_id)
        return p.to_dict() if p else None

    def get_active(self) -> dict | None:
        if self._active_job:
            return self.get_progress(self._active_job)
        return None

    def list_jobs(self, limit: int = 10) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    # ── Start ingestion ───────────────────────────────────────────────────

    async def start_file(self, file_id: int) -> str:
        """
        Start async ingestion of a tracked data_files record.
        Returns a job_id for progress polling.
        """
        if self.is_busy:
            raise RuntimeError(f"Already ingesting (job {self._active_job}). Wait or cancel first.")

        # Look up the file record
        row = await fetch_one("SELECT * FROM data_files WHERE id=?", (file_id,))
        if not row:
            raise FileNotFoundError(f"data_files id={file_id} not found")

        filepath = Path(row["filepath"])
        if not filepath.exists():
            raise FileNotFoundError(f"File not found on disk: {filepath}")

        job_id = f"ingest_{file_id}_{int(time.time())}"
        progress = IngestionProgress(
            job_id=job_id,
            file_id=file_id,
            filename=row["filename"],
            started_at=time.time(),
        )
        self._jobs[job_id] = progress
        self._active_job = job_id

        # Update file status
        await execute(
            "UPDATE data_files SET status='ingesting', ingestion_started=datetime('now') WHERE id=?",
            (file_id,),
        )

        # Fire and forget
        asyncio.create_task(self._run_ingestion(filepath, file_id, progress))
        return job_id

    async def start_from_path(self, filepath: Path, source: str = "cafef") -> str:
        """
        Start ingestion from a raw file path (e.g. dropped ZIP).
        Registers it in data_files first, then ingests.
        """
        if self.is_busy:
            raise RuntimeError(f"Already ingesting (job {self._active_job})")

        if not filepath.exists():
            raise FileNotFoundError(str(filepath))

        # Compute checksum
        checksum = _file_sha256(filepath)

        # Check for duplicate
        existing = await fetch_one(
            "SELECT id FROM data_files WHERE checksum=?", (checksum,)
        )
        if existing:
            log.info("File already registered as data_files id=%d, re-ingesting", existing["id"])
            return await self.start_file(existing["id"])

        # Register
        file_size = filepath.stat().st_size
        file_type = "zip" if filepath.suffix.lower() == ".zip" else "csv"
        await execute(
            """INSERT INTO data_files (filename, filepath, file_size, file_type, source, checksum)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filepath.name, str(filepath), file_size, file_type, source, checksum),
        )
        row = await fetch_one("SELECT id FROM data_files WHERE checksum=?", (checksum,))
        return await self.start_file(row["id"])

    # ── Core ingestion loop ───────────────────────────────────────────────

    async def _run_ingestion(self, filepath: Path, file_id: int, progress: IngestionProgress):
        """The main ingestion coroutine — runs in background."""
        try:
            progress.status = "parsing"
            progress.phase = "Reading file..."

            if filepath.suffix.lower() == ".zip":
                await self._ingest_zip(filepath, file_id, progress)
            else:
                await self._ingest_csv(filepath, file_id, progress)

            progress.status = "completed"
            progress.phase = "Done"

            # Update file record
            await execute(
                """UPDATE data_files SET
                     status='ingested',
                     records_total=?, records_inserted=?, tickers_count=?,
                     date_range_start=?, date_range_end=?,
                     ingestion_completed=datetime('now')
                   WHERE id=?""",
                (progress.records_parsed, progress.records_upserted,
                 progress.tickers_found, progress.date_min, progress.date_max,
                 file_id),
            )

            # Also log to data_sync
            await execute(
                """INSERT INTO data_sync
                   (sync_type, source, started_at, completed_at, status, records_count, tickers_count, details)
                   VALUES ('file_ingest', 'cafef', ?, datetime('now'), 'completed', ?, ?, ?)""",
                (datetime.utcnow().isoformat(), progress.records_upserted,
                 progress.tickers_found, f"file_id={file_id}"),
            )

            log.info(
                "Ingestion complete: %s → %d records, %d tickers in %.1fs",
                filepath.name, progress.records_upserted, progress.tickers_found,
                progress.elapsed_sec,
            )

        except Exception as e:
            progress.status = "failed"
            progress.error = str(e)
            progress.phase = "Failed"
            log.exception("Ingestion failed for file_id=%d", file_id)

            await execute(
                "UPDATE data_files SET status='failed', error_message=? WHERE id=?",
                (str(e), file_id),
            )

        finally:
            self._active_job = None

    async def _ingest_zip(self, filepath: Path, file_id: int, progress: IngestionProgress):
        """Stream-parse a CafeF ZIP, committing in BATCH_SIZE chunks."""
        # Read ZIP from disk (the zip itself is in memory but we parse CSV line-by-line)
        zip_bytes = filepath.read_bytes()
        progress.phase = "Scanning ZIP contents..."

        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile:
            raise ValueError(f"Invalid ZIP file: {filepath.name}")

        # Count total lines first (quick scan) for progress estimation
        total_lines = 0
        csv_names = [n for n in zf.namelist() if not n.endswith("/")]
        for name in csv_names:
            with zf.open(name) as f:
                for _ in f:
                    total_lines += 1
        progress.batches_total = max(1, total_lines // BATCH_SIZE)
        progress.phase = f"Found {total_lines:,} lines in {len(csv_names)} file(s)"

        # Release reference to help GC
        del zip_bytes
        await asyncio.sleep(0)  # yield to event loop

        # Now stream-parse
        batch: list[tuple] = []
        all_tickers: set[str] = set()

        for name in csv_names:
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

                        row = (
                            symbol, iso_date,
                            float(parts[2]), float(parts[3]),
                            float(parts[4]), float(parts[5]),
                            int(float(parts[6])),
                        )
                        batch.append(row)
                        all_tickers.add(symbol)
                        progress.records_parsed += 1

                        # Track date range
                        if not progress.date_min or iso_date < progress.date_min:
                            progress.date_min = iso_date
                        if not progress.date_max or iso_date > progress.date_max:
                            progress.date_max = iso_date

                    except (ValueError, IndexError):
                        continue

                    # Flush batch
                    if len(batch) >= BATCH_SIZE:
                        upserted = await self._flush_batch(batch)
                        progress.records_upserted += upserted
                        progress.batches_done += 1
                        progress.tickers_found = len(all_tickers)
                        progress.phase = f"Batch {progress.batches_done}/{progress.batches_total}"
                        batch = []
                        await asyncio.sleep(0)  # yield to event loop

        # Final partial batch
        if batch:
            upserted = await self._flush_batch(batch)
            progress.records_upserted += upserted
            progress.batches_done += 1

        zf.close()

        # Update stocks table
        progress.phase = "Updating ticker metadata..."
        progress.tickers_found = len(all_tickers)
        await self._update_stocks(all_tickers)

    async def _ingest_csv(self, filepath: Path, file_id: int, progress: IngestionProgress):
        """Stream-parse a raw CSV file (same AmiBroker format)."""
        batch: list[tuple] = []
        all_tickers: set[str] = set()

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
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

                    row = (
                        symbol, iso_date,
                        float(parts[2]), float(parts[3]),
                        float(parts[4]), float(parts[5]),
                        int(float(parts[6])),
                    )
                    batch.append(row)
                    all_tickers.add(symbol)
                    progress.records_parsed += 1

                    if not progress.date_min or iso_date < progress.date_min:
                        progress.date_min = iso_date
                    if not progress.date_max or iso_date > progress.date_max:
                        progress.date_max = iso_date
                except (ValueError, IndexError):
                    continue

                if len(batch) >= BATCH_SIZE:
                    upserted = await self._flush_batch(batch)
                    progress.records_upserted += upserted
                    progress.batches_done += 1
                    progress.tickers_found = len(all_tickers)
                    progress.phase = f"Batch {progress.batches_done}"
                    batch = []
                    await asyncio.sleep(0)

        if batch:
            upserted = await self._flush_batch(batch)
            progress.records_upserted += upserted
            progress.batches_done += 1

        progress.tickers_found = len(all_tickers)
        await self._update_stocks(all_tickers)

    # ── Batch DB operations ───────────────────────────────────────────────

    async def _flush_batch(self, batch: list[tuple]) -> int:
        """Upsert a batch of (symbol, date, O, H, L, C, V) tuples."""
        if not batch:
            return 0

        async with db_session() as db:
            await db.executemany(
                """INSERT OR REPLACE INTO daily_ohlcv
                   (symbol, date, open, high, low, close, volume, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'cafef')""",
                batch,
            )
            await db.commit()

        return len(batch)

    async def _update_stocks(self, tickers: set[str]):
        """Refresh stocks table metadata for affected tickers."""
        async with db_session() as db:
            for t in tickers:
                await db.execute(
                    """INSERT INTO stocks (symbol, first_date, last_date, total_bars, updated_at)
                       VALUES (?,
                         (SELECT MIN(date) FROM daily_ohlcv WHERE symbol=?),
                         (SELECT MAX(date) FROM daily_ohlcv WHERE symbol=?),
                         (SELECT COUNT(*) FROM daily_ohlcv WHERE symbol=?),
                         datetime('now'))
                       ON CONFLICT(symbol) DO UPDATE SET
                         first_date = excluded.first_date,
                         last_date  = excluded.last_date,
                         total_bars = excluded.total_bars,
                         updated_at = excluded.updated_at""",
                    (t, t, t, t),
                )
            await db.commit()
            await asyncio.sleep(0)


# ── Helpers ───────────────────────────────────────────────────────────────

def _file_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Compute SHA256 of a file without loading it all into memory."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# Singleton
ingestion_engine = IngestionEngine()
