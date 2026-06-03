# TickerBoo 📊

> *Do you TickerBoo?* — Peek-a-boo into Vietnamese market data, right inside Excel.

TickerBoo is a self-hosted backend + Excel add-in that brings VN stock market data and technical indicators directly into your spreadsheets as native functions.

```excel
=TB.PRICE("VNM")
=TB.CANDLES("VNM","1d",200)
=TB.RSI("VNM","1d",14)
=TB.MACD("VNM","1d")
```

## Architecture

```
CafeF (historical daily) ──┐
DNSE  (intraday 1m/1H)  ──┤──► Backend (FastAPI) ──► SQLite ──► Indicator Cache
VNDirect (backup)       ──┘         │
                                     ▼
                            Excel Add-in (Office.js)
                            └── TB.* formula functions
                            └── Sidebar monitor + tester
```

## Quickstart (dev)

```bash
git clone https://github.com/econodoo/tickerboo.git
cd tickerboo/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
cd ..
bash backend/run.sh
# → http://localhost:8688/health
# → http://localhost:8688/docs  (OpenAPI)
```

## Deployment

See [docs/deployment.md](docs/deployment.md) for nginx + systemd setup at `tmc.vetami.net/tb`.

## Iteration status

- [x] **Iter 0** — Project skeleton, scripts, logging, health endpoint
- [x] **Iter 1** — Plugin architecture, CafeF harvester, 10 price functions, admin playground
- [x] **Iter 2** — Mock data seeder (15 tickers × 500 days), all functions verified
- [x] **Iter 3** — 54 TA-Lib indicators (RSI, MACD, BB, Ichimoku, SuperTrend, 14 shortcuts)
- [x] **Iter 4** — Interactive charts (Lightweight Charts), /series endpoint, TB.CHART function
- [x] **Iter 5** — Office.js Excel add-in (manifest, auto-gen functions.json/js, taskpane, install guide)
- [x] **Iter 6** — Function call analytics (DB logging, /admin/analytics endpoint)
- [x] **Iter 7** — 5 metadata functions (TICKERS, LAST_DATE, TICKER_INFO, DATA_STATUS, BAR_COUNT) + icons
- [ ] **Iter 4** — Async pre-compute jobs
- [ ] **Iter 5** — Office.js add-in skeleton + TB.* functions
- [ ] **Iter 6** — Sidebar function tester
- [ ] **Iter 7** — DNSE intraday (real 15m/1h) + 1w roller
- [ ] **Iter 8** — Google auth + API key
