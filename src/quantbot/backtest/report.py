"""Backtest report generation (JSON + self-contained HTML).

Renders a :class:`~quantbot.backtest.metrics.BacktestResult` into a JSON summary
and a standalone HTML page with an equity curve, a drawdown chart and a metrics
table. Plotly is used for interactive charts when available; otherwise a
lightweight inline SVG sparkline keeps the report dependency-free.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from quantbot.backtest.metrics import BacktestResult
from quantbot.core.logging import get_logger

_log = get_logger(__name__)


def write_json(result: BacktestResult, path: str | Path) -> Path:
    """Write the result summary + equity curve to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": result.summary(),
        "equity_curve": result.equity_curve,
        "timestamps": result.timestamps,
        "trades": [
            {
                "symbol": t.symbol,
                "side": t.side.value,
                "entry_price": str(t.entry_price),
                "exit_price": str(t.exit_price),
                "net_pnl": str(t.net_pnl),
                "return_pct": str(t.return_pct),
                "exit_reason": t.exit_reason.value,
                "opened_at": t.opened_at.isoformat(),
                "closed_at": t.closed_at.isoformat(),
            }
            for t in result.trades
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _log.info("backtest_json_written", path=str(path))
    return path


def _drawdown_series(equity: list[float]) -> list[float]:
    peak = float("-inf")
    out = []
    for value in equity:
        peak = max(peak, value)
        out.append((peak - value) / peak if peak > 0 else 0.0)
    return out


def write_html(result: BacktestResult, path: str | Path) -> Path:
    """Write a standalone HTML report (interactive if plotly is installed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    charts_html = _charts_html(result)
    metrics_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in result.summary().items()
    )
    html = _HTML_TEMPLATE.format(
        title=f"Backtest — {result.strategy} / {result.symbol}",
        headline=result.headline(),
        charts=charts_html,
        metrics_rows=metrics_rows,
        generated=datetime.now(UTC).isoformat(),
    )
    path.write_text(html, encoding="utf-8")
    _log.info("backtest_html_written", path=str(path))
    return path


def _charts_html(result: BacktestResult) -> str:
    try:
        import plotly.graph_objects as go  # type: ignore
        from plotly.io import to_html  # type: ignore
    except ImportError:
        return _svg_sparkline(result.equity_curve)

    x = result.timestamps or list(range(len(result.equity_curve)))
    equity_fig = go.Figure(go.Scatter(x=x, y=result.equity_curve, mode="lines", name="Equity"))
    equity_fig.update_layout(title="Equity Curve", template="plotly_dark", height=360)
    dd = [-d * 100 for d in _drawdown_series(result.equity_curve)]
    dd_fig = go.Figure(go.Scatter(x=x, y=dd, mode="lines", fill="tozeroy", name="Drawdown %"))
    dd_fig.update_layout(title="Drawdown (%)", template="plotly_dark", height=260)
    return to_html(equity_fig, include_plotlyjs="cdn", full_html=False) + to_html(
        dd_fig, include_plotlyjs=False, full_html=False
    )


def _svg_sparkline(equity: list[float]) -> str:
    """A dependency-free inline SVG equity sparkline."""
    if len(equity) < 2:
        return "<p>Not enough data for a chart.</p>"
    width, height = 800, 240
    lo, hi = min(equity), max(equity)
    span = (hi - lo) or 1.0
    step = width / (len(equity) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - (v - lo) / span * (height - 20) - 10:.1f}"
        for i, v in enumerate(equity)
    )
    return (
        f'<svg width="{width}" height="{height}" style="background:#111">'
        f'<polyline fill="none" stroke="#3fb950" stroke-width="2" points="{points}"/>'
        f"</svg>"
    )


_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ font-family: system-ui, sans-serif; background:#0d1117; color:#e6edf3; margin:0; padding:24px; }}
 h1 {{ font-size:20px; }}
 .headline {{ color:#3fb950; font-family:monospace; margin-bottom:16px; }}
 table {{ border-collapse:collapse; margin-top:16px; }}
 td {{ border:1px solid #30363d; padding:6px 12px; font-family:monospace; }}
 td:first-child {{ color:#8b949e; }}
 .footer {{ color:#484f58; margin-top:24px; font-size:12px; }}
</style></head>
<body>
 <h1>{title}</h1>
 <div class="headline">{headline}</div>
 {charts}
 <h2>Metrics</h2>
 <table>{metrics_rows}</table>
 <div class="footer">Generated {generated} — QuantBot</div>
</body></html>
"""


__all__ = ["write_html", "write_json"]
