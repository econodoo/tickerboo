"""
Screen results page — visual HTML table of screener matches.

  GET /screen?expr=RSI<30              → HTML table of matching tickers
  GET /screen?expr=MA20>MA50+AND+ADX>25 → compound conditions
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from tickerboo.functions.registry import registry
from tickerboo.functions.context import ComputeContext

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/screen", tags=["screen"], response_class=HTMLResponse)
async def screen_page(
    expr: str = Query("RSI<30", description="Screen expression"),
    exchange: str = Query(None, description="Exchange filter: HSX, HNX, UPCOM"),
):
    """Render screener results as an interactive HTML table."""
    ctx = ComputeContext(registry=registry)

    try:
        result = await registry.call("SCREEN", {"expr": expr, "exchange": exchange}, ctx=ctx)
        matches = result.get("value", [])
        duration = result.get("duration_ms", 0)
    except Exception as e:
        return HTMLResponse(f"""<!DOCTYPE html><html><body style="background:#0f1117;color:#ef4444;padding:40px;font-family:sans-serif">
            <h2>Screen Error</h2><p>{e}</p>
            <a href="/screen?expr=RSI%3C30" style="color:#3b82f6">Try: RSI&lt;30</a>
        </body></html>""")

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Screen: {expr} — TickerBoo</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font:13px/1.4 'Segoe UI',sans-serif; background:#0f1117; color:#e5e7eb; }}
  .hdr {{ background:#161922; border-bottom:1px solid #1e2230; padding:12px 20px; display:flex; align-items:center; gap:12px; }}
  .hdr h1 {{ font-size:16px; color:#22c55e; }}
  .hdr a {{ color:#6b7280; text-decoration:none; font-size:12px; }}
  .bar {{ padding:12px 20px; display:flex; gap:8px; align-items:center; background:#0f1117; border-bottom:1px solid #1e2230; }}
  .bar input {{ flex:1; padding:8px 12px; background:#161922; border:1px solid #2d3348; border-radius:6px; color:#e5e7eb; font:13px 'Consolas',monospace; }}
  .bar input:focus {{ outline:none; border-color:#22c55e; }}
  .bar button {{ padding:8px 16px; background:#185B35; color:#fff; border:none; border-radius:6px; font-weight:700; cursor:pointer; }}
  .bar button:hover {{ background:#0d3d22; }}
  .meta {{ padding:8px 20px; color:#6b7280; font-size:12px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; padding:8px 12px; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:#6b7280; border-bottom:2px solid #1e2230; position:sticky; top:0; background:#0f1117; }}
  td {{ padding:6px 12px; border-bottom:1px solid #1e2230; font-size:13px; }}
  tr:hover {{ background:#161922; }}
  .ticker {{ color:#22c55e; font-weight:700; cursor:pointer; }}
  .ticker:hover {{ text-decoration:underline; }}
  .num {{ font-family:'Consolas',monospace; text-align:right; }}
  .pos {{ color:#22c55e; }}
  .neg {{ color:#ef4444; }}
  .empty {{ text-align:center; padding:40px; color:#6b7280; }}
  .presets {{ padding:8px 20px; display:flex; gap:6px; flex-wrap:wrap; }}
  .preset {{ background:#1e2230; border:1px solid #2d3348; border-radius:4px; padding:2px 8px; font-size:11px; color:#9ca3af; cursor:pointer; text-decoration:none; }}
  .preset:hover {{ border-color:#22c55e; color:#22c55e; }}
</style>
</head>
<body>

<div class="hdr">
  <span>🫣</span>
  <h1>TickerBoo Screen</h1>
  <a href="/">Home</a>
  <a href="/admin/playground">Playground</a>
</div>

<div class="bar">
  <input type="text" id="exprInput" value="{expr}" placeholder="RSI<30 AND MA20>MA50"
         onkeydown="if(event.key==='Enter')runScreen()">
  <button onclick="runScreen()">▶ Screen</button>
</div>

<div class="presets">
  <a class="preset" href="/screen?expr=RSI%3C30">RSI&lt;30</a>
  <a class="preset" href="/screen?expr=RSI%3E70">RSI&gt;70</a>
  <a class="preset" href="/screen?expr=CHANGE_PCT%3E0">Up today</a>
  <a class="preset" href="/screen?expr=CHANGE_PCT%3C-2">Down &gt;2%</a>
  <a class="preset" href="/screen?expr=MA20%3EMA50">Uptrend</a>
  <a class="preset" href="/screen?expr=MA20%3CMA50">Downtrend</a>
  <a class="preset" href="/screen?expr=ADX%3E25+AND+RSI%3E50">Strong trend</a>
  <a class="preset" href="/screen?expr=FROM_HIGH52W%3E-5">Near 52w high</a>
  <a class="preset" href="/screen?expr=BB_PERCENT%3C0.1">Below BB lower</a>
</div>

<div class="meta">
  {len(matches)} matches · {duration:.0f}ms · Expression: <code>{expr}</code>
</div>

"""

    if not matches:
        html += '<div class="empty">No tickers match this condition.</div>'
    else:
        # Build table
        # First column is always ticker, rest are indicator values
        if isinstance(matches[0], list):
            # Determine column headers from the first row
            n_cols = len(matches[0])
            # We need to figure out column names from the expression
            import re
            tokens = set()
            for part in re.split(r'\s+(?:AND|OR)\s+', expr, flags=re.IGNORECASE):
                m = re.match(r'^(.+?)\s*(?:<=|>=|<|>|=)\s*(.+)$', part.strip())
                if m:
                    for t in [m.group(1).strip(), m.group(2).strip()]:
                        try:
                            float(t)
                        except ValueError:
                            tokens.add(t.upper())

            cols = ["Ticker"] + sorted(tokens)
            # Pad if needed
            while len(cols) < n_cols:
                cols.append(f"col{len(cols)}")

            html += "<table><tr>"
            for c in cols[:n_cols]:
                html += f"<th>{c}</th>"
            html += "<th></th></tr>"

            for row in matches:
                ticker = row[0] if row else "?"
                html += "<tr>"
                html += f'<td class="ticker" onclick="window.open(\'/chart/{ticker}?overlays=MA20,RSI,BB\',\'_blank\')">{ticker}</td>'
                for val in row[1:]:
                    if val is None:
                        html += '<td class="num" style="color:#374151">—</td>'
                    elif isinstance(val, (int, float)):
                        cls = "pos" if val > 0 else ("neg" if val < 0 else "")
                        html += f'<td class="num {cls}">{val:,.2f}</td>'
                    else:
                        html += f"<td>{val}</td>"
                html += f'<td><a href="/chart/{ticker}?overlays=MA20,RSI,BB" target="_blank" style="color:#3b82f6;font-size:11px">chart</a></td>'
                html += "</tr>"
            html += "</table>"

    html += """
<script>
function runScreen() {
  const expr = document.getElementById('exprInput').value;
  if (expr) window.location.href = '/screen?expr=' + encodeURIComponent(expr);
}
</script>
</body></html>"""

    return HTMLResponse(html)
