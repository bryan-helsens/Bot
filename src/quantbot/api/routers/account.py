"""Account overview: exchange wallet balances vs the bot's own equity, plus the
deposit/withdrawal ledger (capital changes that are NOT counted as profit)."""

from __future__ import annotations

from fastapi import APIRouter

from quantbot.api.dependencies import AuthDep, StateDep
from quantbot.api.schemas import AccountSchema, AssetBalance, CapitalEntry

router = APIRouter(prefix="/account", tags=["account"])


def _capital_history(limit: int = 100) -> list[CapitalEntry]:
    """Reconstruct the deposit/withdrawal ledger from the log ring buffer."""
    from quantbot.core.logging import LOG_BUFFER

    out: list[CapitalEntry] = []
    for entry in LOG_BUFFER.recent(1000):
        if entry.get("event") != "capital_adjusted":
            continue
        data = entry.get("data", {})
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0.0
        equity_after = None
        try:
            equity_after = float(data["equity"]) if "equity" in data else None
        except (TypeError, ValueError):
            equity_after = None
        out.append(CapitalEntry(ts=entry.get("ts"), amount=amount, equity_after=equity_after))
    return out[-limit:]


@router.get("/balances", response_model=AccountSchema)
async def balances(state: StateDep, _: AuthDep) -> AccountSchema:
    """Real exchange balances per asset + wallet-equity vs bot-equity + capital log."""
    quote = state.settings.quote_asset
    engine = state.trading_engine
    if engine is None or not hasattr(engine, "account_overview"):
        pf = state.portfolio
        return AccountSchema(
            quote_asset=quote,
            bot_equity=float(pf.equity()) if pf is not None else 0.0,
            bot_cash=float(pf.cash) if pf is not None else 0.0,
            capital_history=_capital_history(),
        )
    overview = await engine.account_overview()
    return AccountSchema(
        quote_asset=overview.get("quote_asset", quote),
        wallet_equity=overview.get("wallet_equity"),
        bot_equity=overview.get("bot_equity", 0.0),
        bot_cash=overview.get("bot_cash", 0.0),
        assets=[AssetBalance(**a) for a in overview.get("assets", [])],
        capital_history=_capital_history(),
    )


__all__ = ["router"]
