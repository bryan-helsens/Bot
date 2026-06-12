import { api } from "../api/client";
import { cls, holdTime, money, pctRaw, signedMoney } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Analytics, CoinAnalytics } from "../types";

function Breakdown({ title, rows }: { title: string; rows: CoinAnalytics[] }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <div className="empty">No closed trades yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Trades</th>
              <th>Net PnL</th>
              <th>Win%</th>
              <th>Avg win</th>
              <th>Avg loss</th>
              <th>PF</th>
              <th>Fees</th>
              <th>Avg hold</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>
                  {r.trades} <span className="muted">({r.wins}/{r.losses})</span>
                </td>
                <td className={cls(r.net_pnl)}>{signedMoney(r.net_pnl)}</td>
                <td>{pctRaw(r.win_rate * 100)}</td>
                <td className="pos">{money(r.avg_win)}</td>
                <td className="neg">{money(r.avg_loss)}</td>
                <td className={r.profit_factor >= 1 ? "pos" : "neg"}>
                  {r.profit_factor.toFixed(2)}
                </td>
                <td className="muted">{money(r.total_fees)}</td>
                <td>{holdTime(r.avg_hold_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Deep realised-performance breakdown: overall KPIs + per-coin + per-strategy. */
export function TradeAnalytics() {
  const { data } = usePolling<Analytics>(() => api.analytics(), 8000);

  if (!data) {
    return (
      <div className="panel">
        <h2>Trade Analytics</h2>
        <div className="empty">Loading…</div>
      </div>
    );
  }

  const kpis: { label: string; value: string; cls?: string }[] = [
    { label: "Total trades", value: String(data.total_trades) },
    { label: "Net PnL", value: signedMoney(data.net_pnl), cls: cls(data.net_pnl) },
    { label: "Win rate", value: pctRaw(data.win_rate * 100) },
    {
      label: "Profit factor",
      value: data.profit_factor.toFixed(2),
      cls: data.profit_factor >= 1 ? "pos" : "neg",
    },
    { label: "Expectancy / trade", value: signedMoney(data.expectancy), cls: cls(data.expectancy) },
    { label: "Gross profit", value: money(data.gross_profit), cls: "pos" },
    { label: "Gross loss", value: money(data.gross_loss), cls: "neg" },
    { label: "Total fees", value: money(data.total_fees), cls: "muted" },
    { label: "Avg hold time", value: holdTime(data.avg_hold_seconds) },
  ];

  const exits = Object.entries(data.by_exit_reason).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <div className="panel">
        <h2>Trade Analytics — overall</h2>
        <div className="grid">
          {kpis.map((k) => (
            <div className="col-4 stat" key={k.label}>
              <span className="label">{k.label}</span>
              <span className={`value ${k.cls ?? ""}`}>{k.value}</span>
            </div>
          ))}
        </div>
        {exits.length > 0 && (
          <p className="hint">
            Exits:{" "}
            {exits.map(([reason, n]) => (
              <span key={reason}>
                <b>{reason}</b> ×{n}{" "}
              </span>
            ))}
          </p>
        )}
      </div>
      <Breakdown title="Per coin" rows={data.by_coin} />
      <Breakdown title="Per strategy" rows={data.by_strategy} />
    </>
  );
}
