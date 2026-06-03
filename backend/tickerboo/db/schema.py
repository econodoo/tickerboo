"""
TickerBoo database schema.

SQLite with WAL mode. All dates stored as ISO text (YYYY-MM-DD for daily).
The schema is designed to be compatible with DuckDB migration later if needed.
"""

SCHEMA_SQL = """
-- ── Price data ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS daily_ohlcv (
    symbol      TEXT    NOT NULL,
    date        TEXT    NOT NULL,           -- YYYY-MM-DD
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      INTEGER NOT NULL DEFAULT 0,
    source      TEXT    NOT NULL DEFAULT 'cafef',
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_date
    ON daily_ohlcv(symbol, date DESC);

CREATE INDEX IF NOT EXISTS idx_ohlcv_date
    ON daily_ohlcv(date);


-- Weekly OHLCV: rolled from daily by our backend
CREATE TABLE IF NOT EXISTS weekly_ohlcv (
    symbol      TEXT    NOT NULL,
    week_start  TEXT    NOT NULL,           -- YYYY-MM-DD (Monday)
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      INTEGER NOT NULL DEFAULT 0,
    is_complete INTEGER NOT NULL DEFAULT 0, -- 1 if week has ended
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(symbol, week_start)
);

CREATE INDEX IF NOT EXISTS idx_wohlcv_symbol_week
    ON weekly_ohlcv(symbol, week_start DESC);


-- ── Ticker metadata ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS stocks (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    exchange    TEXT,                       -- HSX, HNX, UPCOM
    industry    TEXT,
    first_date  TEXT,                       -- earliest date in daily_ohlcv
    last_date   TEXT,                       -- latest date in daily_ohlcv
    total_bars  INTEGER DEFAULT 0,
    updated_at  TEXT    DEFAULT (datetime('now'))
);


-- ── Sync tracking ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS data_sync (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type       TEXT    NOT NULL,       -- full, catchup, daily
    source          TEXT    NOT NULL,       -- cafef, dnse, vndirect
    started_at      TEXT    NOT NULL,
    completed_at    TEXT,
    status          TEXT    DEFAULT 'running',   -- running, completed, failed
    records_count   INTEGER DEFAULT 0,
    tickers_count   INTEGER DEFAULT 0,
    error_message   TEXT,
    details         TEXT                    -- JSON for extra info
);


-- ── Indicator cache ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS indicator_cache (
    symbol      TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,           -- 1d, 1w (EoD only for now)
    indicator   TEXT    NOT NULL,           -- RSI, MACD_LINE, BB_UPPER etc.
    params_hash TEXT    NOT NULL,           -- deterministic hash of params
    date        TEXT    NOT NULL,           -- date of the bar this value is for
    value       REAL,
    is_locked   INTEGER NOT NULL DEFAULT 0, -- 1 when underlying candle is permanent
    computed_at TEXT    DEFAULT (datetime('now')),
    UNIQUE(symbol, timeframe, indicator, params_hash, date)
);

CREATE INDEX IF NOT EXISTS idx_ic_lookup
    ON indicator_cache(symbol, timeframe, indicator, params_hash, date DESC);


-- ── Function usage analytics ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS function_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    function_name   TEXT    NOT NULL,
    called_at       TEXT    DEFAULT (datetime('now')),
    ticker          TEXT,
    timeframe       TEXT,
    params_json     TEXT,                   -- JSON of all params
    duration_ms     REAL,
    cache_hit       INTEGER DEFAULT 0,
    source_ip       TEXT
);

CREATE INDEX IF NOT EXISTS idx_fc_name ON function_calls(function_name);
CREATE INDEX IF NOT EXISTS idx_fc_time ON function_calls(called_at);
"""
