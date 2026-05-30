import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { Trade } from "../types";

function cls(value: string): string {
  const n = parseFloat(value);
  return n > 0 ? "pos" : n < 0 ? "neg" : "";
}

export function ClosedTrades() {
  const { data, error } = usePolling<Trade[]>(() => api.trades(50), 10000);
  const trades = data ?? [];

  return (
    <div className="panel">
      <h2>Recent Trades</h2>
      {error && <div className="error">{error}</div>}
      {trades.length === 0 ? (
        <div className="empty">No closed trades yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Net PnL</th>
              <th>Return</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id}>
                <td>{t.symbol}</td>
                <td className={t.side === "long" ? "pos" : "neg"}>{t.side}</td>
                <td>{parseFloat(t.entry_price).toFixed(2)}</td>
                <td>{parseFloat(t.exit_price).toFixed(2)}</td>
                <td className={cls(t.net_pnl)}>{parseFloat(t.net_pnl).toFixed(2)}</td>
                <td className={cls(t.return_pct)}>
                  {(parseFloat(t.return_pct) * 100).toFixed(2)}%
                </td>
                <td>{t.exit_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
