import type { Portfolio } from "../types";

function pct(value: string): string {
  return `${(parseFloat(value) * 100).toFixed(2)}%`;
}

function cls(value: string): string {
  const n = parseFloat(value);
  return n > 0 ? "pos" : n < 0 ? "neg" : "";
}

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
    { label: "Equity", value: parseFloat(portfolio.equity).toFixed(2) },
    {
      label: "Total Return",
      value: pct(portfolio.total_return_pct),
      cls: cls(portfolio.total_return_pct),
    },
    {
      label: "Unrealized PnL",
      value: parseFloat(portfolio.unrealized_pnl).toFixed(2),
      cls: cls(portfolio.unrealized_pnl),
    },
    {
      label: "Realized PnL",
      value: parseFloat(portfolio.realized_pnl).toFixed(2),
      cls: cls(portfolio.realized_pnl),
    },
    { label: "Exposure", value: pct(portfolio.exposure_pct) },
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
