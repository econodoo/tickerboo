"""
Data management routes — file upload, ingestion, DB info, settings.

  GET  /admin/data                → Data management HTML page
  POST /admin/data/upload         → Upload a ZIP/CSV file
  GET  /admin/data/files          → List tracked data files
  DELETE /admin/data/files/{id}   → Remove a data file
  POST /admin/data/ingest/{id}    → Start async ingestion from file
  GET  /admin/data/ingest/status  → Active ingestion progress
  GET  /admin/data/ingest/history → Recent ingestion jobs
  GET  /admin/data/db-info        → Database size, table row counts
  GET  /admin/data/settings       → Data source settings
  PUT  /admin/data/settings       → Update data source settings
  GET  /admin/data/functions/search → Fuzzy function search
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from tickerboo.config import settings
from tickerboo.db.session import fetch_one, fetch_all, execute
from tickerboo.sources.ingest import ingestion_engine, _file_sha256

log = logging.getLogger(__name__)

router = APIRouter()

# Data uploads directory
UPLOADS_DIR = Path(settings.db_path).parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ── Page ─────────────────────────────────────────────────────────────────────

@router.get("/admin/data", tags=["data"], response_class=HTMLResponse)
async def data_management_page():
    """Serve the data management HTML page."""
    html_path = Path(__file__).parent.parent / "static" / "data.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Data management page not found</h2>", status_code=404)


# ── File upload ──────────────────────────────────────────────────────────────

@router.post("/admin/data/upload", tags=["data"])
async def upload_data_file(file: UploadFile = File(...)):
    """
    Upload a CafeF ZIP or CSV file for ingestion.

    The file is saved to data/uploads/ and registered in data_files table.
    Call POST /admin/data/ingest/{id} to start processing.
    """
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".zip", ".csv", ".txt"):
        raise HTTPException(400, f"Unsupported file type: {ext}. Use .zip or .csv")

    # Save to uploads dir
    dest = UPLOADS_DIR / file.filename
    counter = 1
    while dest.exists():
        stem = Path(file.filename).stem
        dest = UPLOADS_DIR / f"{stem}_{counter}{ext}"
        counter += 1

    content = await file.read()
    dest.write_bytes(content)
    file_size = len(content)

    # Compute checksum
    import hashlib
    checksum = hashlib.sha256(content).hexdigest()

    # Check for duplicate
    existing = await fetch_one("SELECT id, filename FROM data_files WHERE checksum=?", (checksum,))
    if existing:
        dest.unlink()  # remove duplicate
        return {
            "status": "duplicate",
            "message": f"File identical to existing '{existing['filename']}' (id={existing['id']})",
            "file_id": existing["id"],
        }

    file_type = "zip" if ext == ".zip" else "csv"
    await execute(
        """INSERT INTO data_files (filename, filepath, file_size, file_type, source, checksum)
           VALUES (?, ?, ?, ?, 'cafef', ?)""",
        (dest.name, str(dest), file_size, file_type, checksum),
    )
    row = await fetch_one("SELECT id FROM data_files WHERE checksum=?", (checksum,))

    log.info("Uploaded data file: %s (%d KB) → id=%d", dest.name, file_size // 1024, row["id"])

    return {
        "status": "uploaded",
        "file_id": row["id"],
        "filename": dest.name,
        "size_kb": round(file_size / 1024, 1),
        "message": f"File saved. POST /admin/data/ingest/{row['id']} to start processing.",
    }


# ── File listing ─────────────────────────────────────────────────────────────

@router.get("/admin/data/files", tags=["data"])
async def list_data_files():
    """List all tracked data files with their status."""
    rows = await fetch_all(
        """SELECT id, filename, file_size, file_type, source, uploaded_at, status,
                  records_total, records_inserted, tickers_count,
                  date_range_start, date_range_end,
                  ingestion_started, ingestion_completed, error_message
           FROM data_files ORDER BY id DESC"""
    )
    return {"count": len(rows), "files": rows}


@router.delete("/admin/data/files/{file_id}", tags=["data"])
async def delete_data_file(file_id: int):
    """Delete a data file record and its physical file."""
    row = await fetch_one("SELECT filepath FROM data_files WHERE id=?", (file_id,))
    if not row:
        raise HTTPException(404, f"File id={file_id} not found")

    # Remove physical file
    fpath = Path(row["filepath"])
    if fpath.exists():
        fpath.unlink()

    await execute("DELETE FROM data_files WHERE id=?", (file_id,))
    return {"status": "deleted", "file_id": file_id}


# ── Ingestion control ────────────────────────────────────────────────────────

@router.post("/admin/data/ingest/{file_id}", tags=["data"])
async def start_ingestion(file_id: int):
    """Start async ingestion from a tracked data file."""
    try:
        job_id = await ingestion_engine.start_file(file_id)
        return {
            "status": "started",
            "job_id": job_id,
            "message": "Ingestion running. Poll GET /admin/data/ingest/status for progress.",
        }
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/admin/data/ingest-and-upload", tags=["data"])
async def upload_and_ingest(file: UploadFile = File(...)):
    """Upload a file AND immediately start ingestion (one-step shortcut)."""
    # Upload first
    upload_result = await upload_data_file(file)
    if upload_result.get("status") == "duplicate":
        file_id = upload_result["file_id"]
    else:
        file_id = upload_result["file_id"]

    # Start ingestion
    try:
        job_id = await ingestion_engine.start_file(file_id)
        return {
            "status": "started",
            "job_id": job_id,
            "file_id": file_id,
            "filename": upload_result.get("filename", ""),
        }
    except RuntimeError as e:
        return {
            "status": "queued",
            "file_id": file_id,
            "message": str(e),
        }


@router.get("/admin/data/ingest/status", tags=["data"])
async def ingestion_status():
    """Get active ingestion progress."""
    active = ingestion_engine.get_active()
    return {
        "is_busy": ingestion_engine.is_busy,
        "active": active,
    }


@router.get("/admin/data/ingest/history", tags=["data"])
async def ingestion_history():
    """Recent ingestion jobs (in-memory, current session only)."""
    return {"jobs": ingestion_engine.list_jobs()}


# ── DB info ──────────────────────────────────────────────────────────────────

@router.get("/admin/data/db-info", tags=["data"])
async def db_info():
    """Database size, table row counts, and storage breakdown."""
    db_path = settings.db_path

    # Physical file sizes
    db_size = db_path.stat().st_size if db_path.exists() else 0
    wal_path = Path(str(db_path) + "-wal")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    shm_path = Path(str(db_path) + "-shm")
    shm_size = shm_path.stat().st_size if shm_path.exists() else 0

    # Uploads dir size
    uploads_size = sum(
        f.stat().st_size for f in UPLOADS_DIR.iterdir() if f.is_file()
    ) if UPLOADS_DIR.exists() else 0

    # Table row counts
    tables = {}
    for tbl in ["daily_ohlcv", "weekly_ohlcv", "stocks", "data_sync",
                 "indicator_cache", "function_calls", "data_files", "app_settings"]:
        row = await fetch_one(f"SELECT COUNT(*) as cnt FROM {tbl}")
        tables[tbl] = row["cnt"] if row else 0

    # OHLCV summary
    ohlcv = await fetch_one(
        """SELECT COUNT(DISTINCT symbol) as tickers,
                  COUNT(*) as bars,
                  MIN(date) as earliest,
                  MAX(date) as latest
           FROM daily_ohlcv"""
    )

    # Page count (approximate table sizes)
    page_info = await fetch_one("PRAGMA page_count")
    page_size_info = await fetch_one("PRAGMA page_size")
    page_count = page_info["page_count"] if page_info else 0
    page_size = page_size_info["page_size"] if page_size_info else 4096

    return {
        "db_path": str(db_path),
        "db_size_mb": round(db_size / 1024 / 1024, 2),
        "wal_size_mb": round(wal_size / 1024 / 1024, 2),
        "total_size_mb": round((db_size + wal_size + shm_size) / 1024 / 1024, 2),
        "uploads_size_mb": round(uploads_size / 1024 / 1024, 2),
        "page_count": page_count,
        "page_size": page_size,
        "tables": tables,
        "ohlcv_summary": dict(ohlcv) if ohlcv else {},
    }


# ── Data settings ────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    cafef_url_prefix: str | None = None


@router.get("/admin/data/settings", tags=["data"])
async def get_data_settings():
    """Get current data source settings."""
    # Read from app_settings table, fall back to config defaults
    rows = await fetch_all("SELECT key, value FROM app_settings WHERE key LIKE 'data.%'")
    stored = {r["key"]: r["value"] for r in rows}

    return {
        "cafef_url_prefix": stored.get("data.cafef_url_prefix", settings.cafef_url_prefix),
        "uploads_dir": str(UPLOADS_DIR),
    }


@router.put("/admin/data/settings", tags=["data"])
async def update_data_settings(req: SettingsUpdate):
    """Update data source settings."""
    updated = {}

    if req.cafef_url_prefix is not None:
        url = req.cafef_url_prefix.strip().rstrip("/") + "/"
        await execute(
            """INSERT INTO app_settings (key, value, updated_at)
               VALUES ('data.cafef_url_prefix', ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (url,),
        )
        # Also update runtime config
        settings.cafef_url_prefix = url
        updated["cafef_url_prefix"] = url
        log.info("Updated CafeF URL prefix to: %s", url)

    return {"status": "updated", "settings": updated}


# ── Purge / reset ────────────────────────────────────────────────────────────

@router.post("/admin/data/purge-ohlcv", tags=["data"])
async def purge_ohlcv(source: str = Query("all", description="Source to purge: cafef, mock, all")):
    """Delete OHLCV data (dangerous!). Use for re-ingestion from scratch."""
    if source == "all":
        await execute("DELETE FROM daily_ohlcv")
        await execute("DELETE FROM stocks")
    else:
        await execute("DELETE FROM daily_ohlcv WHERE source=?", (source,))
        # Clean up stocks for removed tickers
        await execute(
            """DELETE FROM stocks WHERE symbol NOT IN
               (SELECT DISTINCT symbol FROM daily_ohlcv)"""
        )

    return {"status": "purged", "source": source}


# ── Function search (fuzzy) ──────────────────────────────────────────────────

# Alias map for fuzzy matching
FUNCTION_ALIASES = {
    "ichi": ["ICHIMOKU", "TENKAN", "KIJUN", "SENKOU_A", "SENKOU_B", "CHIKOU"],
    "ichimoku": ["ICHIMOKU", "TENKAN", "KIJUN", "SENKOU_A", "SENKOU_B", "CHIKOU"],
    "cloud": ["ICHIMOKU", "SENKOU_A", "SENKOU_B"],
    "alli": ["SUPERTREND", "SUPERTREND_VAL", "SUPERTREND_DIR"],  # alligator-style trend
    "alligator": ["SUPERTREND", "SUPERTREND_VAL", "SUPERTREND_DIR"],
    "boll": ["BBANDS", "BB_UPPER", "BB_MIDDLE", "BB_LOWER", "BB_WIDTH", "BB_PERCENT"],
    "bollinger": ["BBANDS", "BB_UPPER", "BB_MIDDLE", "BB_LOWER", "BB_WIDTH", "BB_PERCENT"],
    "bb": ["BBANDS", "BB_UPPER", "BB_MIDDLE", "BB_LOWER", "BB_WIDTH", "BB_PERCENT"],
    "band": ["BBANDS", "BB_UPPER", "BB_MIDDLE", "BB_LOWER", "BB_WIDTH", "BB_PERCENT"],
    "macd": ["MACD", "MACD_LINE", "MACD_SIGNAL", "MACD_HIST"],
    "stoch": ["STOCH", "STOCH_K", "STOCH_D"],
    "stochastic": ["STOCH", "STOCH_K", "STOCH_D"],
    "super": ["SUPERTREND", "SUPERTREND_VAL", "SUPERTREND_DIR"],
    "supertrend": ["SUPERTREND", "SUPERTREND_VAL", "SUPERTREND_DIR"],
    "trend": ["SUPERTREND", "SUPERTREND_VAL", "SUPERTREND_DIR", "ADX", "PSAR"],
    "parabolic": ["PSAR"],
    "sar": ["PSAR"],
    "moving": ["SMA", "EMA", "WMA", "DEMA", "TEMA"],
    "average": ["SMA", "EMA", "WMA", "DEMA", "TEMA"],
    "ma": ["SMA", "EMA", "WMA", "DEMA", "TEMA", "MA5", "MA10", "MA20", "MA50", "MA100", "MA200"],
    "vol": ["VOL", "VOL_MA", "OBV", "AD", "VOLUME"],
    "volume": ["VOL", "VOL_MA", "OBV", "AD"],
    "rsi": ["RSI", "RSI7", "RSI14", "RSI21"],
    "momentum": ["RSI", "MACD", "STOCH", "CCI", "MFI", "ADX", "WILLR", "ROC", "MOM"],
    "price": ["PRICE", "OPEN", "HIGH", "LOW", "CLOSE", "OHLC", "OHLCV", "CANDLES"],
    "candle": ["CANDLES", "OHLC", "OHLCV"],
    "snap": ["SNAPSHOT", "SNAPSHOT_TABLE"],
    "screen": ["SCREEN"],
    "chart": ["CHART"],
    "52": ["HIGH52W", "LOW52W", "FROM_HIGH52W", "FROM_LOW52W"],
    "week": ["HIGH52W", "LOW52W", "FROM_HIGH52W", "FROM_LOW52W"],
    "range": ["RANGE", "ATR", "NATR"],
    "atr": ["ATR", "NATR"],
    "change": ["CHANGE", "CHANGE_PCT"],
    "percent": ["CHANGE_PCT", "BB_PERCENT", "FROM_HIGH52W", "FROM_LOW52W"],
    "obv": ["OBV"],
    "ad": ["AD"],
    "cci": ["CCI"],
    "mfi": ["MFI", "MFI14"],
    "adx": ["ADX"],
    "will": ["WILLR"],
    "williams": ["WILLR"],
    "roc": ["ROC"],
    "mom": ["MOM", "MOMENTUM"],
    "info": ["TICKER_INFO", "DATA_STATUS", "BAR_COUNT"],
    "ticker": ["TICKERS", "TICKER_INFO"],
    "meta": ["TICKERS", "LAST_DATE", "TICKER_INFO", "DATA_STATUS", "BAR_COUNT"],
    "status": ["DATA_STATUS"],
    "date": ["LAST_DATE"],
}


@router.get("/admin/data/functions/search", tags=["data"])
async def search_functions(q: str = Query("", description="Search query (partial name, alias, keyword)")):
    """
    Fuzzy function search — matches partial names, aliases, and keywords.

    Examples:
      ?q=ichi → all Ichimoku components
      ?q=bb   → all Bollinger Band functions
      ?q=rsi  → RSI + shortcut variants
    """
    from tickerboo.functions.registry import registry

    if not q.strip():
        return {"query": q, "results": registry.list_all()}

    q_lower = q.strip().lower()
    all_fns = registry.list_all()

    # Build match set
    matched_names: set[str] = set()
    scores: dict[str, int] = {}  # name → match quality (higher = better)

    # 1. Exact alias match
    if q_lower in FUNCTION_ALIASES:
        for name in FUNCTION_ALIASES[q_lower]:
            matched_names.add(name)
            scores[name] = scores.get(name, 0) + 100

    # 2. Prefix alias match (e.g. "ichi" matches "ichimoku" key)
    #    Only alias_key.startswith(query), NOT query.startswith(alias_key)
    #    to prevent "macd" leaking into "ma" aliases
    for alias_key, alias_fns in FUNCTION_ALIASES.items():
        if alias_key != q_lower and alias_key.startswith(q_lower) and len(q_lower) >= 2:
            for name in alias_fns:
                matched_names.add(name)
                scores[name] = scores.get(name, 0) + 80

    # 3. Direct name match (prefix, contains, exact)
    for fn in all_fns:
        name_lower = fn["name"].lower()

        if name_lower == q_lower:
            matched_names.add(fn["name"])
            scores[fn["name"]] = scores.get(fn["name"], 0) + 200  # exact = highest
        elif name_lower.startswith(q_lower):
            matched_names.add(fn["name"])
            scores[fn["name"]] = scores.get(fn["name"], 0) + 90
        elif q_lower in name_lower:
            matched_names.add(fn["name"])
            scores[fn["name"]] = scores.get(fn["name"], 0) + 50

    # 4. Description / category match
    for fn in all_fns:
        desc_lower = (fn.get("description") or "").lower()
        cat_lower = (fn.get("category") or "").lower()
        if q_lower in desc_lower or q_lower in cat_lower:
            matched_names.add(fn["name"])
            scores[fn["name"]] = scores.get(fn["name"], 0) + 30

    # 5. Multi-keyword: split query and match ALL parts
    parts = q_lower.split()
    if len(parts) > 1:
        for fn in all_fns:
            search_text = f"{fn['name']} {fn.get('description', '')} {fn.get('category', '')}".lower()
            if all(part in search_text for part in parts):
                matched_names.add(fn["name"])
                scores[fn["name"]] = scores.get(fn["name"], 0) + 60

    # Build results sorted by score
    results = []
    for fn in all_fns:
        if fn["name"] in matched_names:
            fn_copy = dict(fn)
            fn_copy["_score"] = scores.get(fn["name"], 0)
            results.append(fn_copy)

    results.sort(key=lambda x: (-x["_score"], x["name"]))

    # Remove internal score from output
    for r in results:
        r.pop("_score", None)

    return {
        "query": q,
        "count": len(results),
        "results": results,
    }
