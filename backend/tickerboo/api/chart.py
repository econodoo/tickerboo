"""
Chart endpoint — generates interactive HTML chart pages.

  GET /chart/{ticker}?tf=1d&n=200&overlays=RSI,MA20,BB
  → Full-page interactive candlestick chart with overlays

  TB.CHART("VNM","1d",200,"RSI,MA20")
  → Returns the chart URL as a string
"""
from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from tickerboo.functions.registry import registry
from tickerboo.functions.context import ComputeContext

log = logging.getLogger(__name__)
router = APIRouter()


# ── Overlay definitions ──────────────────────────────────────────────────────

OVERLAY_DEFS = {
    # Overlays on main price chart (line series)
    "MA5":   {"fn": "SMA", "params": {"period": 5},  "pane": "main", "color": "#f59e0b"},
    "MA10":  {"fn": "SMA", "params": {"period": 10}, "pane": "main", "color": "#84cc16"},
    "MA20":  {"fn": "SMA", "params": {"period": 20}, "pane": "main", "color": "#3b82f6"},
    "MA50":  {"fn": "SMA", "params": {"period": 50}, "pane": "main", "color": "#a855f7"},
    "MA100": {"fn": "SMA", "params": {"period": 100},"pane": "main", "color": "#ec4899"},
    "MA200": {"fn": "SMA", "params": {"period": 200},"pane": "main", "color": "#ef4444"},
    "EMA12": {"fn": "EMA", "params": {"period": 12}, "pane": "main", "color": "#22d3ee"},
    "EMA26": {"fn": "EMA", "params": {"period": 26}, "pane": "main", "color": "#f97316"},
    "BB":    {"fn": "BBANDS", "params": {"period": 20, "stddev": 2.0}, "pane": "main", "type": "band"},

    # Sub-pane indicators
    "RSI":   {"fn": "RSI", "params": {"period": 14}, "pane": "sub", "color": "#8b5cf6",
              "levels": [30, 70]},
    "MFI":   {"fn": "MFI", "params": {"period": 14}, "pane": "sub", "color": "#06b6d4",
              "levels": [20, 80]},
}


async def _compute_series(ticker: str, tf: str, candles: list, overlay_key: str) -> dict | None:
    """Compute indicator series for all candle dates."""
    odef = OVERLAY_DEFS.get(overlay_key.upper())
    if not odef:
        return None

    ctx = ComputeContext(registry=registry)
    fn_name = odef["fn"]
    params = odef["params"].copy()

    # For series computation, we run the indicator on the full candle set
    # by computing it once at the end with enough lookback
    plugin = registry.get(fn_name)
    if not plugin:
        return None

    try:
        import numpy as np
        import talib
        from tickerboo.functions.helpers import get_ohlcv_arrays

        n = len(candles)
        closes = np.array([c["close"] for c in candles], dtype=np.float64)
        highs = np.array([c["high"] for c in candles], dtype=np.float64)
        lows = np.array([c["low"] for c in candles], dtype=np.float64)
        volumes = np.array([c["vol"] for c in candles], dtype=np.float64)

        result = {"key": overlay_key.upper(), **odef}

        if fn_name == "SMA":
            arr = talib.SMA(closes, timeperiod=params["period"])
            result["data"] = _arr_to_series(candles, arr)
        elif fn_name == "EMA":
            arr = talib.EMA(closes, timeperiod=params["period"])
            result["data"] = _arr_to_series(candles, arr)
        elif fn_name == "RSI":
            arr = talib.RSI(closes, timeperiod=params["period"])
            result["data"] = _arr_to_series(candles, arr)
        elif fn_name == "MFI":
            arr = talib.MFI(highs, lows, closes, volumes, timeperiod=params["period"])
            result["data"] = _arr_to_series(candles, arr)
        elif fn_name == "BBANDS":
            upper, middle, lower = talib.BBANDS(
                closes, timeperiod=params["period"], nbdevup=params["stddev"], nbdevdn=params["stddev"]
            )
            result["upper"] = _arr_to_series(candles, upper)
            result["middle"] = _arr_to_series(candles, middle)
            result["lower"] = _arr_to_series(candles, lower)
        else:
            return None

        return result
    except Exception as e:
        log.warning("Chart overlay %s failed: %s", overlay_key, e)
        return None


def _arr_to_series(candles: list, arr) -> list:
    """Convert numpy array to [{time, value}] for Lightweight Charts."""
    import math
    result = []
    for i, c in enumerate(candles):
        v = float(arr[i])
        if not math.isnan(v):
            result.append({"time": c["time"], "value": round(v, 2)})
    return result


# ── Chart endpoint ───────────────────────────────────────────────────────────

@router.get("/chart/{ticker}", tags=["chart"], response_class=HTMLResponse)
async def render_chart(
    ticker: str,
    tf: str = Query("1d", description="Timeframe"),
    n: int = Query(200, description="Number of bars", ge=20, le=2000),
    overlays: str = Query("MA20", description="Comma-separated overlays: MA20,RSI,BB,EMA12,MA50"),
):
    """Render interactive candlestick chart with overlays."""
    ticker = ticker.upper()

    # Fetch candle data
    ctx = ComputeContext(registry=registry)
    try:
        raw_candles = await ctx.candles(ticker, tf, n)
    except Exception as e:
        return HTMLResponse(f"<h2>Error: {e}</h2>", status_code=400)

    if not raw_candles:
        return HTMLResponse(f"<h2>No data for {ticker}</h2>", status_code=404)

    # Format candles for Lightweight Charts
    candle_data = []
    volume_data = []
    for c in raw_candles:
        t = c.date  # ISO date string
        candle_data.append({
            "time": t, "open": c.open, "high": c.high,
            "low": c.low, "close": c.close,
        })
        volume_data.append({
            "time": t, "value": c.volume,
            "color": "rgba(34,197,94,0.3)" if c.close >= c.open else "rgba(239,68,68,0.3)",
        })

    # Candle dicts for overlay computation
    candle_dicts = [{"time": c.date, "open": c.open, "high": c.high,
                     "low": c.low, "close": c.close, "vol": c.volume} for c in raw_candles]

    # Compute overlays
    overlay_keys = [o.strip().upper() for o in overlays.split(",") if o.strip()]
    overlay_results = []
    for key in overlay_keys:
        result = await _compute_series(ticker, tf, candle_dicts, key)
        if result:
            overlay_results.append(result)

    # Render HTML
    html = _render_chart_html(ticker, tf, n, candle_data, volume_data, overlay_results)
    return HTMLResponse(html)


# ── TB.CHART function plugin ────────────────────────────────────────────────

from tickerboo.functions.base import FunctionPlugin, Param, PARAM_TICKER, PARAM_TF, PARAM_N
from tickerboo.functions.registry import register


@register
class ChartURL(FunctionPlugin):
    name = "CHART"
    category = "chart"
    tier = "simple"
    description = "Returns URL to interactive chart page."
    examples = [
        '=TB.CHART("VNM")                  → /chart/VNM?tf=1d&n=200&overlays=MA20',
        '=TB.CHART("VNM","1d",500,"RSI,BB") → /chart/VNM?tf=1d&n=500&overlays=RSI,BB',
    ]
    params = [
        PARAM_TICKER, PARAM_TF, PARAM_N,
        Param("overlays", "string", default="MA20", desc="Comma-separated: MA20,RSI,BB,EMA12,MA50"),
    ]
    output = "text"

    async def compute(self, ctx, *, ticker, tf="1d", n=200, overlays="MA20"):
        return f"/chart/{ticker.upper()}?tf={tf}&n={n}&overlays={overlays}"


# ── HTML template ────────────────────────────────────────────────────────────

def _render_chart_html(ticker, tf, n, candles, volumes, overlays):
    candle_json = json.dumps(candles)
    volume_json = json.dumps(volumes)
    overlays_json = json.dumps(overlays, default=str)

    # Which overlays go on main chart vs sub-panes
    main_overlays = [o for o in overlays if o.get("pane") == "main"]
    sub_overlays = [o for o in overlays if o.get("pane") == "sub"]

    overlay_names = ", ".join(o.get("key", "?") for o in overlays)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{ticker} {tf.upper()} — TickerBoo Chart</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0f1117; color:#e5e7eb; font:13px/1.4 'SF Mono','Consolas',monospace; }}
  .header {{ display:flex; align-items:center; gap:12px; padding:10px 16px; background:#161922; border-bottom:1px solid #1e2230; }}
  .header h1 {{ font-size:16px; color:#22c55e; }}
  .header .meta {{ color:#6b7280; font-size:12px; }}
  .header .overlays {{ color:#9ca3af; font-size:11px; margin-left:auto; }}
  .header a {{ color:#3b82f6; text-decoration:none; font-size:12px; }}
  #main-chart {{ width:100%; }}
  #sub-chart {{ width:100%; }}
  .powered {{ text-align:center; padding:8px; color:#374151; font-size:10px; }}
  .powered a {{ color:#6b7280; }}
</style>
</head>
<body>

<div class="header">
  <h1>🫣 {ticker}</h1>
  <span class="meta">{tf.upper()} · {len(candles)} bars</span>
  <span class="overlays">{overlay_names}</span>
  <a href="/admin/playground">↩ Playground</a>
</div>

<div id="main-chart"></div>
<div id="sub-chart"></div>

<div class="powered">
  Powered by <a href="https://github.com/econodoo/tickerboo" target="_blank">TickerBoo</a>
  · Data from CafeF · Charts by Lightweight Charts
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<script>
const candles = {candle_json};
const volumes = {volume_json};
const overlayDefs = {overlays_json};

// ── Main chart ──────────────────────────────────────────────────────────
const mainH = Math.max(400, window.innerHeight * 0.55);
const mainEl = document.getElementById('main-chart');
const chart = LightweightCharts.createChart(mainEl, {{
  width: mainEl.offsetWidth,
  height: mainH,
  layout: {{ background: {{ color: '#0f1117' }}, textColor: '#9ca3af' }},
  grid: {{ vertLines: {{ color: '#1e2230' }}, horzLines: {{ color: '#1e2230' }} }},
  crosshair: {{ mode: 0 }},
  rightPriceScale: {{ borderColor: '#2d3348' }},
  timeScale: {{ borderColor: '#2d3348', timeVisible: false }},
}});

// Candles
const candleSeries = chart.addCandlestickSeries({{
  upColor: '#22c55e', downColor: '#ef4444',
  borderUpColor: '#22c55e', borderDownColor: '#ef4444',
  wickUpColor: '#22c55e', wickDownColor: '#ef4444',
}});
candleSeries.setData(candles);

// Volume
const volumeSeries = chart.addHistogramSeries({{
  priceFormat: {{ type: 'volume' }},
  priceScaleId: 'vol',
}});
chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.85, bottom: 0 }} }});
volumeSeries.setData(volumes);

// Main overlays (MAs, Bollinger Bands)
overlayDefs.filter(o => o.pane === 'main').forEach(ov => {{
  if (ov.type === 'band' && ov.upper && ov.lower) {{
    // Bollinger Bands
    const upper = chart.addLineSeries({{ color: 'rgba(59,130,246,0.4)', lineWidth: 1, priceLineVisible: false }});
    upper.setData(ov.upper);
    const middle = chart.addLineSeries({{ color: 'rgba(59,130,246,0.6)', lineWidth: 1, lineStyle: 2, priceLineVisible: false }});
    middle.setData(ov.middle);
    const lower = chart.addLineSeries({{ color: 'rgba(59,130,246,0.4)', lineWidth: 1, priceLineVisible: false }});
    lower.setData(ov.lower);
  }} else if (ov.data) {{
    const line = chart.addLineSeries({{
      color: ov.color || '#3b82f6',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
      title: ov.key,
    }});
    line.setData(ov.data);
  }}
}});

// ── Sub-pane chart (RSI, MFI) ───────────────────────────────────────────
const subOverlays = overlayDefs.filter(o => o.pane === 'sub');
if (subOverlays.length > 0) {{
  const subEl = document.getElementById('sub-chart');
  const subH = 150;
  const subChart = LightweightCharts.createChart(subEl, {{
    width: subEl.offsetWidth,
    height: subH,
    layout: {{ background: {{ color: '#0f1117' }}, textColor: '#6b7280' }},
    grid: {{ vertLines: {{ color: '#1e2230' }}, horzLines: {{ color: '#1e2230' }} }},
    crosshair: {{ mode: 0 }},
    rightPriceScale: {{ borderColor: '#2d3348' }},
    timeScale: {{ borderColor: '#2d3348', timeVisible: false, visible: true }},
  }});

  subOverlays.forEach(ov => {{
    if (ov.data) {{
      const line = subChart.addLineSeries({{
        color: ov.color || '#8b5cf6',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: ov.key,
      }});
      line.setData(ov.data);

      // Level lines (RSI 30/70 etc)
      if (ov.levels) {{
        ov.levels.forEach(lv => {{
          line.createPriceLine({{
            price: lv,
            color: 'rgba(107,114,128,0.4)',
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
          }});
        }});
      }}
    }}
  }});

  // Sync crosshair
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
    if (range) subChart.timeScale().setVisibleLogicalRange(range);
  }});
  subChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
    if (range) chart.timeScale().setVisibleLogicalRange(range);
  }});
}}

// Responsive
window.addEventListener('resize', () => {{
  chart.applyOptions({{ width: mainEl.offsetWidth }});
  const subEl = document.getElementById('sub-chart');
  if (subOverlays.length > 0 && subEl.firstChild) {{
    // sub chart resize handled by its own instance
  }}
}});

chart.timeScale().fitContent();
</script>
</body>
</html>"""
