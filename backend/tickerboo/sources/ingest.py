"""
Async data ingestion engine — turbo mode for full sync, patch mode for updates.

FULL SYNC (turbo):
  - Raw sqlite3 in thread pool (no aiosqlite overhead)
  - Single BEGIN/COMMIT transaction
  - Plain INSERT (no conflict check — DB is empty or we don't care)
  - PRAGMA synchronous=OFF + temp_store=MEMORY
  - Drop indexes before, recreate after
  - 100K-record batches inside the transaction
  - Stocks metadata updated with single aggregate query at end
  - Target: 1.5M records in ~60-90 seconds

PATCH MODE (incremental):
  - INSERT OR IGNORE (skip existing, only add new)
  - Keeps indexes active
  - Smaller batches (10K)
  - Used for daily catchup / fill gaps

Usage:
    engine = IngestionEngine()
    job_id = await engine.start_file(file_id, mode="full")   # turbo
    job_id = await engine.start_file(file_id, mode="patch")  # incremental
    status = engine.get_progress(job_id)
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from tickerboo.config import settings
from tickerboo.db.session import fetch_one, fetch_all, execute

log = logging.getLogger(__name__)

TURBO_BATCH = 100_000   # records per executemany in turbo mode
PATCH_BATCH = 10_000    # records per executemany in patch mode
_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ingest")


@dataclass
class IngestionProgress:
    """Live progress for an in-flight ingestion job."""
    job_id: str
    file_id: int
    filename: str
    mode: str = "full"
    status: str = "pending"
    phase: str = ""
    records_parsed: int = 0
    records_inserted: int = 0
    batches_done: int = 0
    batches_total: int = 0
    tickers_found: int = 0
    started_at: float = 0.0
    elapsed_sec: float = 0.0
    error: str = ""
    date_min: str = ""
    date_max: str = ""
    rate_rps: int = 0            # records per second

    def to_dict(self) -> dict:
        now = time.time()
        self.elapsed_sec = round(now - self.started_at, 1) if self.started_at else 0
        if self.elapsed_sec > 0:
            self.rate_rps = int(self.records_inserted / self.elapsed_sec)
        return {
            "job_id": self.job_id, "file_id": self.file_id,
            "filename": self.filename, "mode": self.mode,
            "status": self.status, "phase": self.phase,
            "records_parsed": self.records_parsed,
            "records_inserted": self.records_inserted,
            "batches_done": self.batches_done,
            "batches_total": self.batches_total,
            "tickers_found": self.tickers_found,
            "elapsed_sec": self.elapsed_sec,
            "rate_rps": self.rate_rps,
            "error": self.error,
            "date_min": self.date_min, "date_max": self.date_max,
        }


class IngestionEngine:
    """Manages async data ingestion with turbo and patch modes."""

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

    async def start_file(self, file_id: int, mode: str = "full") -> str:
        """
        Start async ingestion. mode='full' for turbo, 'patch' for incremental.
        Returns job_id for progress polling.
        """
        if self.is_busy:
            raise RuntimeError(f"Already ingesting (job {self._active_job}). Wait or cancel.")

        row = await fetch_one("SELECT * FROM data_files WHERE id=?", (file_id,))
        if not row:
            raise FileNotFoundError(f"data_files id={file_id} not found")

        filepath = Path(row["filepath"])
        if not filepath.exists():
            raise FileNotFoundError(f"File not on disk: {filepath}")

        job_id = f"ingest_{file_id}_{int(time.time())}"
        progress = IngestionProgress(
            job_id=job_id, file_id=file_id,
            filename=row["filename"], mode=mode,
            started_at=time.time(),
        )
        self._jobs[job_id] = progress
        self._active_job = job_id

        await execute(
            "UPDATE data_files SET status='ingesting', ingestion_started=datetime('now') WHERE id=?",
            (file_id,),
        )

        # Run in thread pool — raw sqlite3, no event loop blocking
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            _thread_pool,
            self._run_ingestion_sync,
            filepath, file_id, mode, progress,
        )
        return job_id

    async def start_from_path(self, filepath: Path, source: str = "cafef",
                              mode: str = "full") -> str:
        """Start ingestion from a raw path. Registers in data_files first."""
        if self.is_busy:
            raise RuntimeError(f"Already ingesting (job {self._active_job})")
        if not filepath.exists():
            raise FileNotFoundError(str(filepath))

        checksum = _file_sha256(filepath)
        existing = await fetch_one(
            "SELECT id FROM data_files WHERE checksum=?", (checksum,)
        )
        if existing:
            return await self.start_file(existing["id"], mode=mode)

        file_size = filepath.stat().st_size
        file_type = "zip" if filepath.suffix.lower() == ".zip" else "csv"
        await execute(
            """INSERT INTO data_files (filename, filepath, file_size, file_type, source, checksum)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filepath.name, str(filepath), file_size, file_type, source, checksum),
        )
        row = await fetch_one("SELECT id FROM data_files WHERE checksum=?", (checksum,))
        return await self.start_file(row["id"], mode=mode)

    # ── Core ingestion (runs in thread, raw sqlite3) ──────────────────────

    def _run_ingestion_sync(self, filepath: Path, file_id: int,
                            mode: str, progress: IngestionProgress):
        """
        The SYNCHRONOUS ingestion worker — runs in a thread pool.
        Uses raw sqlite3 for maximum throughput.
        """
        db_path = str(settings.db_path)

        try:
            progress.status = "parsing"
            progress.phase = "Opening file..."

            # ── Parse all records from ZIP/CSV ────────────────────────
            records, tickers_set = self._parse_file(filepath, progress)

            if not records:
                progress.status = "completed"
                progress.phase = "No records found"
                self._finish_file(file_id, progress)
                return

            progress.records_parsed = len(records)
            progress.tickers_found = len(tickers_set)
            batch_size = TURBO_BATCH if mode == "full" else PATCH_BATCH
            progress.batches_total = (len(records) + batch_size - 1) // batch_size
            progress.phase = f"Inserting {len(records):,} records ({mode} mode)..."
            progress.status = "ingesting"

            # ── Open raw sqlite3 connection ───────────────────────────
            conn = sqlite3.connect(db_path, timeout=60)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")

            if mode == "full":
                self._turbo_insert(conn, records, batch_size, progress)
            else:
                self._patch_insert(conn, records, batch_size, progress)

            # ── Update stocks metadata (single aggregate query) ───────
            progress.phase = "Updating ticker metadata..."
            conn.execute("""
                INSERT OR REPLACE INTO stocks (symbol, first_date, last_date, total_bars, updated_at)
                SELECT symbol,
                       MIN(date), MAX(date), COUNT(*),
                       datetime('now')
                FROM daily_ohlcv
                GROUP BY symbol
            """)
            conn.commit()
            conn.close()

            progress.status = "completed"
            progress.phase = "Done"
            elapsed = time.time() - progress.started_at
            rps = int(progress.records_inserted / elapsed) if elapsed > 0 else 0
            log.info(
                "Ingestion complete: %s → %d records, %d tickers in %.1fs (%d rps)",
                filepath.name, progress.records_inserted,
                progress.tickers_found, elapsed, rps,
            )
            self._finish_file(file_id, progress)

        except Exception as e:
            progress.status = "failed"
            progress.error = str(e)
            progress.phase = "Failed"
            log.exception("Ingestion failed for file_id=%d", file_id)
            self._finish_file(file_id, progress)

        finally:
            self._active_job = None

    def _turbo_insert(self, conn: sqlite3.Connection,
                      records: list[tuple], batch_size: int,
                      progress: IngestionProgress):
        """
        TURBO MODE: max throughput for full sync.
        - Drop indexes
        - synchronous=OFF
        - Plain INSERT (no conflict check)
        - Single giant transaction
        - Recreate indexes after
        """
        log.info("Turbo insert: %d records, batch=%d", len(records), batch_size)

        # Aggressive pragmas for bulk load
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

        # Drop indexes (huge speedup for bulk insert)
        conn.execute("DROP INDEX IF EXISTS idx_ohlcv_symbol_date")
        conn.execute("DROP INDEX IF EXISTS idx_ohlcv_date")

        # Single transaction for everything
        conn.execute("BEGIN TRANSACTION")
        try:
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                conn.executemany(
                    """INSERT INTO daily_ohlcv
                       (symbol, date, open, high, low, close, volume, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'cafef')""",
                    batch,
                )
                progress.records_inserted += len(batch)
                progress.batches_done += 1
                progress.phase = f"Batch {progress.batches_done}/{progress.batches_total} ({progress.records_inserted:,} rows)"

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Recreate indexes
        progress.phase = "Rebuilding indexes..."
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_date "
            "ON daily_ohlcv(symbol, date DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ohlcv_date "
            "ON daily_ohlcv(date)"
        )
        conn.commit()

        # Restore safe pragmas
        conn.execute("PRAGMA synchronous=NORMAL")

    def _patch_insert(self, conn: sqlite3.Connection,
                      records: list[tuple], batch_size: int,
                      progress: IngestionProgress):
        """
        PATCH MODE: incremental update — skip existing rows.
        Keeps indexes active, uses INSERT OR IGNORE.
        """
        log.info("Patch insert: %d records, batch=%d", len(records), batch_size)

        conn.execute("BEGIN TRANSACTION")
        try:
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                conn.executemany(
                    """INSERT OR IGNORE INTO daily_ohlcv
                       (symbol, date, open, high, low, close, volume, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'cafef')""",
                    batch,
                )
                progress.records_inserted += len(batch)
                progress.batches_done += 1
                progress.phase = f"Patch {progress.batches_done}/{progress.batches_total}"
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ── File parsing (ZIP/CSV → tuples) ───────────────────────────────────

    def _parse_file(self, filepath: Path, progress: IngestionProgress
                    ) -> tuple[list[tuple], set[str]]:
        """Parse ZIP or CSV into list of (symbol, date, O, H, L, C, V) tuples."""
        if filepath.suffix.lower() == ".zip":
            return self._parse_zip(filepath, progress)
        else:
            return self._parse_csv(filepath, progress)

    def _parse_zip(self, filepath: Path, progress: IngestionProgress
                   ) -> tuple[list[tuple], set[str]]:
        """Stream-parse a ZIP without loading full CSV into memory."""
        records: list[tuple] = []
        tickers: set[str] = set()

        progress.phase = "Scanning ZIP..."
        with zipfile.ZipFile(str(filepath)) as zf:
            csv_names = [n for n in zf.namelist() if not n.endswith("/")]
            progress.phase = f"Parsing {len(csv_names)} file(s)..."

            for name in csv_names:
                with zf.open(name) as f:
                    for raw_line in f:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line or line[0] in ("<", "!"):
                            continue
                        parts = line.split(",")
                        if len(parts) < 7:
                            continue
                        try:
                            symbol = parts[0].strip().upper()
                            ds = parts[1].strip()
                            if len(ds) != 8:
                                continue
                            iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"

                            records.append((
                                symbol, iso,
                                float(parts[2]), float(parts[3]),
                                float(parts[4]), float(parts[5]),
                                int(float(parts[6])),
                            ))
                            tickers.add(symbol)

                            # Track date range
                            if not progress.date_min or iso < progress.date_min:
                                progress.date_min = iso
                            if not progress.date_max or iso > progress.date_max:
                                progress.date_max = iso

                        except (ValueError, IndexError):
                            continue

                        # Update progress every 100K lines
                        if len(records) % 100_000 == 0:
                            progress.records_parsed = len(records)
                            progress.tickers_found = len(tickers)
                            progress.phase = f"Parsed {len(records):,} records..."

        log.info("Parsed %d records, %d tickers from %s",
                 len(records), len(tickers), filepath.name)
        return records, tickers

    def _parse_csv(self, filepath: Path, progress: IngestionProgress
                   ) -> tuple[list[tuple], set[str]]:
        """Parse a raw CSV file."""
        records: list[tuple] = []
        tickers: set[str] = set()

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line[0] in ("<", "!"):
                    continue
                parts = line.split(",")
                if len(parts) < 7:
                    continue
                try:
                    symbol = parts[0].strip().upper()
                    ds = parts[1].strip()
                    if len(ds) != 8:
                        continue
                    iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
                    records.append((
                        symbol, iso,
                        float(parts[2]), float(parts[3]),
                        float(parts[4]), float(parts[5]),
                        int(float(parts[6])),
                    ))
                    tickers.add(symbol)
                    if not progress.date_min or iso < progress.date_min:
                        progress.date_min = iso
                    if not progress.date_max or iso > progress.date_max:
                        progress.date_max = iso
                except (ValueError, IndexError):
                    continue

        return records, tickers

    # ── Finish helpers ────────────────────────────────────────────────────

    def _finish_file(self, file_id: int, progress: IngestionProgress):
        """Update data_files and data_sync tables (runs in thread, raw sqlite3)."""
        for attempt in range(3):
            try:
                conn = sqlite3.connect(str(settings.db_path), timeout=60)
                conn.execute("PRAGMA busy_timeout=30000")
                status = progress.status

                if status == "completed":
                    conn.execute(
                        """UPDATE data_files SET
                             status='ingested', records_total=?, records_inserted=?,
                             tickers_count=?, date_range_start=?, date_range_end=?,
                             ingestion_completed=datetime('now'), error_message=NULL
                           WHERE id=?""",
                        (progress.records_parsed, progress.records_inserted,
                         progress.tickers_found, progress.date_min, progress.date_max,
                         file_id),
                    )
                    conn.execute(
                        """INSERT INTO data_sync
                           (sync_type, source, started_at, completed_at, status,
                            records_count, tickers_count, details)
                           VALUES ('file_ingest', 'cafef', ?, datetime('now'),
                                   'completed', ?, ?, ?)""",
                        (datetime.utcnow().isoformat(),
                         progress.records_inserted, progress.tickers_found,
                         f"file_id={file_id} mode={progress.mode}"),
                    )
                else:
                    conn.execute(
                        "UPDATE data_files SET status='failed', error_message=? WHERE id=?",
                        (progress.error, file_id),
                    )

                # Also clean up any stale 'running' syncs from cafef path
                conn.execute(
                    """UPDATE data_sync SET status='aborted', completed_at=datetime('now'),
                          error_message='Superseded by file ingestion'
                       WHERE status='running' AND started_at < datetime('now', '-2 minutes')"""
                )

                conn.commit()
                conn.close()
                log.info("File status updated: id=%d → %s", file_id, status)
                return
            except Exception as e:
                log.warning("_finish_file attempt %d failed: %s", attempt + 1, e)
                import time as _t
                _t.sleep(1)

        log.error("_finish_file FAILED after 3 attempts for id=%d", file_id)


# ── Helpers ───────────────────────────────────────────────────────────────

def _file_sha256(filepath: Path, chunk_size: int = 65536) -> str:
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
