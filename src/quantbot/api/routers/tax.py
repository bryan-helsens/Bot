"""Tax / fiscaal report — the realised-gain data a Belgian declaration needs.

Belgian crypto tax (2026): a frequent-trading bot almost certainly falls under
*speculative* income (33%, Box XV) rather than the 10% private-wealth regime, and
the foreign Binance account must be reported to the CAP + Box XIII. This endpoint
gives the per-year realised figures and a per-trade ledger (CSV) for an accountant.

NOTE: amounts reflect whatever the bot traded — on testnet that's play-money and
nothing is declarable. It becomes relevant only for real-money trading.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC
from decimal import Decimal

from fastapi import APIRouter, Response

from quantbot.api.dependencies import AuthDep, StateDep, trade_history

router = APIRouter(prefix="/tax", tags=["tax"])


def _year(t) -> int:
    ts = t.closed_at
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).year


@router.get("/report")
async def tax_report(state: StateDep, _: AuthDep) -> dict:
    """Per-calendar-year realised result (the basis for a tax declaration)."""
    trades = trade_history(state)
    quote = state.settings.quote_asset
    by_year: dict[int, dict] = {}
    for t in trades:
        y = _year(t)
        bucket = by_year.setdefault(
            y, {"year": y, "trades": 0, "realized_pnl": Decimal("0"),
                 "gross_profit": Decimal("0"), "gross_loss": Decimal("0"),
                 "fees": Decimal("0"), "wins": 0, "losses": 0}
        )
        bucket["trades"] += 1
        bucket["realized_pnl"] += t.net_pnl
        bucket["fees"] += t.fees
        if t.net_pnl > 0:
            bucket["gross_profit"] += t.net_pnl
            bucket["wins"] += 1
        elif t.net_pnl < 0:
            bucket["gross_loss"] += t.net_pnl
            bucket["losses"] += 1

    # Capital deposits/withdrawals (NOT income — for reconciliation only).
    from quantbot.core.logging import LOG_BUFFER

    deposits_by_year: dict[int, Decimal] = {}
    for entry in LOG_BUFFER.recent(2000):
        if entry.get("event") != "capital_adjusted":
            continue
        ts = entry.get("ts")
        if not ts:
            continue
        try:
            amount = Decimal(str(entry.get("data", {}).get("amount", "0")))
            yr = int(ts[:4])
        except (ValueError, TypeError, ArithmeticError):
            continue
        deposits_by_year[yr] = deposits_by_year.get(yr, Decimal("0")) + amount

    years = [
        {
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in b.items()},
            "capital_added": str(deposits_by_year.get(b["year"], Decimal("0"))),
        }
        for b in sorted(by_year.values(), key=lambda b: b["year"], reverse=True)
    ]
    return {
        "quote_asset": quote,
        "is_testnet": bool(state.settings.binance.testnet),
        "years": years,
        "notes": {
            "regime": "Een frequent handelende bot valt in België vrijwel zeker onder "
                      "SPECULATIEVE/diverse inkomsten (33%), niet het 10%-privéregime.",
            "declare": "Diverse inkomsten → Vak XV. Beroepsmatig → Vak XVII.",
            "foreign_account": "Binance (buitenlandse rekening) melden bij het CAP (NBB) "
                               "én aankruisen in Vak XIII-A van je aangifte.",
            "testnet": "Testnet = nepgeld; niets aan te geven. Alleen relevant bij echt geld.",
            "disclaimer": "Geen fiscaal advies — raadpleeg een boekhouder/fiscalist.",
        },
    }


@router.get("/trades.csv")
async def tax_trades_csv(state: StateDep, _: AuthDep) -> Response:
    """Per-trade ledger as CSV (acquisition/disposal, cost, proceeds, gain) for an accountant."""
    trades = trade_history(state)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "opened_at", "closed_at", "symbol", "side", "quantity",
        "entry_price", "exit_price", "cost", "proceeds", "fees", "net_pnl", "exit_reason",
    ])
    for t in sorted(trades, key=lambda x: x.closed_at):
        cost = t.quantity * t.entry_price
        proceeds = t.quantity * t.exit_price
        writer.writerow([
            t.opened_at.isoformat(), t.closed_at.isoformat(), t.symbol, t.side.value,
            str(t.quantity), str(t.entry_price), str(t.exit_price),
            str(cost), str(proceeds), str(t.fees), str(t.net_pnl),
            t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=quantbot_trades.csv"},
    )


__all__ = ["router"]
