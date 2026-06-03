# 🫣 TickerBoo

**VN Stock Market Data & Analytics for Excel**

79 `TB.*` custom functions delivered through an Office.js add-in, backed by a self-hosted Python backend. Think Bloomberg Terminal, but free, for Vietnamese retail traders, and it runs in your existing Excel.

```
=TB.PRICE("VNM")                     → 124,500
=TB.RSI("FPT", "1d", 14)             → 50.2
=TB.CANDLES("HPG", "1d", 20)         → spills 20×6 table
=TB.SCREEN("RSI<30 AND MA20>MA50")   → matching tickers
=TB.SNAPSHOT_TABLE("VNM,FPT,HPG")    → dashboard table
```

> **Do you TickerBoo?**

---

## Quick start

```bash
git clone https://github.com/econodoo/tickerboo.git
cd tickerboo/backend
pip install -r requirements.txt --break-system-packages
python manage.py serve               # starts on :8688

# Load data (pick one):
python manage.py seed                 # mock data — instant
curl -X POST localhost:8688/admin/sync/full      # real CafeF data — ~2 min

# Open in browser:
open http://localhost:8688               # landing page
open http://localhost:8688/admin/playground  # function tester
open http://localhost:8688/chart/VNM?overlays=MA20,RSI,BB  # interactive chart
open http://localhost:8688/screen?expr=RSI%3C30  # screener
```

## Excel Add-in

The add-in files are **auto-generated from the plugin registry** — adding a Python plugin file = function immediately available in Excel. Zero build step.

1. Open Excel → **Insert** → **My Add-ins** → **Upload My Add-in**
2. Point to: `http://localhost:8688/addin/manifest.xml`
3. Type `=TB.PRICE("VNM")` in any cell

The add-in provides:
- 79 `TB.*` custom functions with Excel autocomplete
- Sidebar (taskpane) with function browser + formula insert
- Array results use Excel dynamic array spill

## Function reference (79 functions)

### Price (16)
| Function | Example | Returns |
|---|---|---|
| `PRICE` | `=TB.PRICE("VNM")` | Latest closing price |
| `OPEN/HIGH/LOW/CLOSE/VOL` | `=TB.CLOSE("VNM")` | Single OHLCV component |
| `OHLC` | `=TB.OHLC("VNM")` | [O, H, L, C] |
| `OHLCV` | `=TB.OHLCV("VNM")` | [O, H, L, C, V] |
| `CANDLES` | `=TB.CANDLES("VNM","1d",20)` | 20×6 table (date,O,H,L,C,V) |
| `RANGE` | `=TB.RANGE("VNM","2025-01-01","2025-01-31")` | Date range table |
| `CHANGE` | `=TB.CHANGE("VNM")` | Absolute price change |
| `CHANGE_PCT` | `=TB.CHANGE_PCT("VNM")` | % change from previous bar |
| `HIGH52W / LOW52W` | `=TB.HIGH52W("VNM")` | 52-week high/low |
| `FROM_HIGH52W / FROM_LOW52W` | `=TB.FROM_HIGH52W("VNM")` | % from 52-week extreme |

### Moving Averages (5)
| Function | Example | Description |
|---|---|---|
| `SMA` | `=TB.SMA("VNM","1d",20)` | Simple Moving Average |
| `EMA` | `=TB.EMA("VNM","1d",20)` | Exponential Moving Average |
| `WMA` | `=TB.WMA("VNM","1d",20)` | Weighted Moving Average |
| `DEMA` | `=TB.DEMA("VNM","1d",20)` | Double EMA |
| `TEMA` | `=TB.TEMA("VNM","1d",20)` | Triple EMA |

### Momentum (14)
| Function | Example | Description |
|---|---|---|
| `RSI` | `=TB.RSI("VNM","1d",14)` | Relative Strength Index (0-100) |
| `MACD` | `=TB.MACD("VNM")` | [MACD, Signal, Histogram] |
| `MACD_LINE/SIGNAL/HIST` | `=TB.MACD_LINE("VNM")` | Individual MACD components |
| `STOCH` | `=TB.STOCH("VNM")` | Stochastic [%K, %D] |
| `STOCH_K / STOCH_D` | `=TB.STOCH_K("VNM")` | Individual stochastic |
| `CCI` | `=TB.CCI("VNM")` | Commodity Channel Index |
| `MFI` | `=TB.MFI("VNM")` | Money Flow Index (volume-weighted RSI) |
| `ADX` | `=TB.ADX("VNM")` | Average Directional Index (trend strength) |
| `WILLR` | `=TB.WILLR("VNM")` | Williams %R |
| `ROC / MOM` | `=TB.ROC("VNM")` | Rate of Change / Momentum |

### Volatility (8)
| Function | Example | Description |
|---|---|---|
| `ATR / NATR` | `=TB.ATR("VNM")` | Average True Range / Normalized ATR |
| `BBANDS` | `=TB.BBANDS("VNM")` | Bollinger Bands [Upper, Middle, Lower] |
| `BB_UPPER/MIDDLE/LOWER` | `=TB.BB_UPPER("VNM")` | Individual band |
| `BB_WIDTH / BB_PERCENT` | `=TB.BB_PERCENT("VNM")` | Band width / %B position |

### Volume (3)
`OBV`, `AD`, `VOL_MA`

### Composite (12)
| Function | Example | Description |
|---|---|---|
| `ICHIMOKU` | `=TB.ICHIMOKU("VNM")` | [Tenkan, Kijun, Senkou A, Senkou B, Chikou] |
| `TENKAN/KIJUN/SENKOU_A/SENKOU_B/CHIKOU` | Individual components |
| `SUPERTREND` | `=TB.SUPERTREND("VNM")` | [Value, Direction (+1/-1)] |
| `PSAR` | `=TB.PSAR("VNM")` | Parabolic SAR |
| `SNAPSHOT` | `=TB.SNAPSHOT("VNM")` | [Close, Chg%, RSI, MACD, Trend, ADX, VolR, 52wH%, Signal] |
| `SNAPSHOT_TABLE` | `=TB.SNAPSHOT_TABLE("VNM,FPT,HPG")` | Multi-ticker dashboard |

### Shortcuts (14)
`RSI14`, `RSI7`, `RSI21`, `MA5`, `MA10`, `MA20`, `MA50`, `MA100`, `MA200`, `EMA12`, `EMA26`, `EMA50`, `EMA200`, `MFI14`

### Metadata (5)
| Function | Example | Description |
|---|---|---|
| `TICKERS` | `=TB.TICKERS()` | All available symbols (spills) |
| `LAST_DATE` | `=TB.LAST_DATE("VNM")` | Latest trading date |
| `TICKER_INFO` | `=TB.TICKER_INFO("VNM")` | [name, exchange, industry, ...] |
| `DATA_STATUS` | `=TB.DATA_STATUS()` | [tickers, bars, earliest, latest] |
| `BAR_COUNT` | `=TB.BAR_COUNT("VNM")` | Number of available bars |

### Screen (1)
```
=TB.SCREEN("RSI<30")                   → oversold tickers
=TB.SCREEN("RSI<30 AND MA20>MA50")     → oversold + uptrend
=TB.SCREEN("CHANGE_PCT>3")             → up >3% today
=TB.SCREEN("FROM_HIGH52W>-5")          → near 52-week high
=TB.SCREEN("ADX>25 AND RSI>50")        → strong trend + bullish
```

### Chart (1)
`=TB.CHART("VNM","1d",200,"RSI,MA20")` → returns chart page URL

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Landing page |
| `GET` | `/functions` | List all registered functions |
| `POST` | `/call/{name}` | Call a function: `{"args":{"ticker":"VNM"}}` |
| `POST` | `/series/{name}` | Full time series: `{"args":{"ticker":"VNM"},"n":200}` |
| `GET` | `/tickers` | List available tickers |
| `GET` | `/chart/{ticker}` | Interactive chart page |
| `GET` | `/screen?expr=RSI<30` | Screener results page |
| `GET` | `/addin/manifest.xml` | Excel add-in manifest |
| `GET` | `/addin/functions.json` | Auto-generated function metadata |
| `GET` | `/addin/install` | Install guide |
| `GET` | `/admin/playground` | Function tester |
| `GET` | `/admin/analytics` | Usage statistics |
| `POST` | `/admin/seed` | Seed mock data |
| `POST` | `/admin/sync/full` | Full CafeF historical sync |
| `GET` | `/docs` | OpenAPI docs |

## Architecture

```
tickerboo/
├── backend/
│   ├── tickerboo/
│   │   ├── main.py                 # FastAPI app
│   │   ├── config.py               # Settings (env, paths)
│   │   ├── db/                     # SQLite (aiosqlite, WAL mode)
│   │   ├── sources/                # Data: CafeF harvester + mock seeder
│   │   ├── functions/              # Plugin system
│   │   │   ├── base.py             # FunctionPlugin base class
│   │   │   ├── registry.py         # Auto-discovery + call dispatch
│   │   │   ├── context.py          # ComputeContext (candle access)
│   │   │   ├── helpers.py          # numpy array helpers
│   │   │   ├── price/              # 16 price functions
│   │   │   ├── ma/                 # 5 moving averages
│   │   │   ├── momentum/           # 14 momentum indicators
│   │   │   ├── volatility/         # 8 volatility indicators
│   │   │   ├── volume/             # 3 volume indicators
│   │   │   ├── composite/          # 12 composite (Ichimoku, SuperTrend, Snapshot)
│   │   │   ├── shortcuts/          # 14 preset shortcuts
│   │   │   ├── metadata/           # 5 metadata functions
│   │   │   └── screen/             # 1 screener (mini-DSL)
│   │   ├── api/                    # Route handlers
│   │   │   ├── functions.py        # /call, /series, /functions
│   │   │   ├── chart.py            # /chart/{ticker}
│   │   │   ├── screen.py           # /screen?expr=
│   │   │   ├── addin.py            # /addin/* (auto-gen manifest, functions.json/js)
│   │   │   └── admin.py            # /admin/* (sync, stats, analytics, playground)
│   │   └── static/                 # HTML pages + icons
│   ├── run.sh                      # Dev server launcher
│   └── requirements.txt
├── scripts/                        # Deployment scripts
├── systemd/                        # tickerboo.service
├── nginx/                          # Reverse proxy config
└── docs/                           # deployment.md
```

**Key design principle**: `add plugin file → function appears everywhere`. The registry auto-discovers plugins via `pkgutil.walk_packages`, and the add-in files are auto-generated from the registry at request time.

## Stack

- **Python 3.11+** / FastAPI / uvicorn / aiosqlite
- **TA-Lib 0.6.8** — 50+ technical indicators (pre-built wheels, no C build)
- **SQLite WAL** — zero-config, single-file database
- **Office.js** — Excel custom functions + taskpane
- **Lightweight Charts** — interactive candlestick charts (TradingView)
- **CafeF CDN** — VN stock daily OHLCV data (AmiBroker format, since 2000)

## Iteration history

- [x] **Iter 0** — Project skeleton, scripts, logging, health endpoint
- [x] **Iter 1** — Plugin architecture, CafeF harvester, 10 price functions, admin playground
- [x] **Iter 2** — Mock data seeder (15 tickers × 500 days)
- [x] **Iter 3** — 54 TA-Lib indicators (RSI, MACD, BB, Ichimoku, SuperTrend, 14 shortcuts)
- [x] **Iter 4** — Interactive charts (Lightweight Charts), /series endpoint, TB.CHART
- [x] **Iter 5** — Office.js Excel add-in (manifest, auto-gen functions.json/js, taskpane)
- [x] **Iter 6** — Function call analytics (DB logging, /admin/analytics)
- [x] **Iter 7** — Metadata functions (TICKERS, LAST_DATE, TICKER_INFO) + icons + install guide
- [x] **Iter 8** — Trading functions (CHANGE, HIGH52W, FROM_HIGH52W) + landing page
- [x] **Iter 9** — TB.SCREEN screener with mini-DSL + screen results page
- [x] **Iter 10** — TB.SNAPSHOT + TB.SNAPSHOT_TABLE (one-formula dashboard)

## License

MIT
