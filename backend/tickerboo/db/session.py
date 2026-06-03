"""
Database session management for TickerBoo.

Uses aiosqlite for async access. Single-file SQLite with WAL mode.
"""
from __future__ import annotations

import logging
import aiosqlite
from contextlib import asynccontextmanager

from tickerboo.config import settings

log = logging.getLogger(__name__)

# Module-level connection (single-writer pattern for SQLite)
_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    """Create tables if they don't exist. Call once at startup."""
    from .schema import SCHEMA_SQL

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Initialising DB at %s", settings.db_path)

    async with aiosqlite.connect(str(settings.db_path)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA_SQL)
        await db.commit()

    log.info("DB schema ready")


async def get_db() -> aiosqlite.Connection:
    """Get (or create) the shared DB connection."""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(settings.db_path))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA busy_timeout=5000")
    return _db


async def close_db() -> None:
    """Close the shared connection. Call at shutdown."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        log.info("DB connection closed")


@asynccontextmanager
async def db_session():
    """Context manager for DB operations that need their own connection."""
    db = await aiosqlite.connect(str(settings.db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    try:
        yield db
    finally:
        await db.close()


# ── Query helpers ────────────────────────────────────────────────────────────

async def fetch_one(query: str, params: tuple = ()) -> dict | None:
    """Execute query and return first row as dict, or None."""
    db = await get_db()
    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    """Execute query and return all rows as list of dicts."""
    db = await get_db()
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def execute(query: str, params: tuple = ()) -> int:
    """Execute a write query and return rows affected."""
    db = await get_db()
    cursor = await db.execute(query, params)
    await db.commit()
    return cursor.rowcount


async def executemany(query: str, params_list: list[tuple]) -> int:
    """Execute a write query for many rows."""
    db = await get_db()
    await db.executemany(query, params_list)
    await db.commit()
    return len(params_list)
