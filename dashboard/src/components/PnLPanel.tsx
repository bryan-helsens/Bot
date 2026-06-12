import { cls, money, pct, signedMoney } from "../format";
import type { Portfolio } from "../types";

export function PnLPanel({ portfolio }: { portfolio: Portfolio | null }) {
  if (!portfolio) {
    return (
      <div className="panel">
        <h2>Portfolio</h2>
        <div className="empty">Loading…</div>
      </div>
    );
  }
  const cards: { label: string; value: string; cls?: string }[] = [
    { label: "Equity", value: money(portfolio.equity) },
    { label: "Cash (free)", value: money(portfolio.cash) },
    {
      label: "Total Return",
      value: pct(portfolio.total_return_pct),
      cls: cls(portfolio.total_return_pct),
    },
    {
      label: "Unrealized PnL",
      value: signedMoney(portfolio.unrealized_pnl),
      cls: cls(portfolio.unrealized_pnl),
    },
    {
      label: "Realized PnL",
      value: signedMoney(portfolio.realized_pnl),
      cls: cls(portfolio.realized_pnl),
    },
    { label: "Exposure", value: `${money(portfolio.exposure)} (${pct(portfolio.exposure_pct)})` },
    { label: "Max Drawdown", value: pct(portfolio.max_drawdown), cls: "neg" },
  ];

  return (
    <div className="panel">
      <h2>Portfolio</h2>
      <div className="grid">
        {cards.map((c) => (
          <div className="col-4 stat" key={c.label}>
            <span className="label">{c.label}</span>
            <span className={`value ${c.cls ?? ""}`}>{c.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
