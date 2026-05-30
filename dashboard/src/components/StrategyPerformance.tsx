import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { StrategyPerformance as Perf } from "../types";

export function StrategyPerformance() {
  const { data, error } = usePolling<Perf[]>(() => api.strategyPerformance(), 15000);
  const rows = data ?? [];

  return (
    <div className="panel">
      <h2>Strategy Performance</h2>
      {error && <div className="error">{error}</div>}
      {rows.length === 0 ? (
        <div className="empty">No strategy results yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Net Profit</th>
              <th>PF</th>
              <th>Win%</th>
              <th>Sharpe</th>
              <th>MaxDD</th>
              <th>Trades</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.strategy}>
                <td>{r.strategy}</td>
                <td className={r.net_profit >= 0 ? "pos" : "neg"}>
                  {r.net_profit.toFixed(2)}
                </td>
                <td>{r.profit_factor.toFixed(2)}</td>
                <td>{(r.win_rate * 100).toFixed(1)}%</td>
                <td>{r.sharpe_ratio.toFixed(2)}</td>
                <td className="neg">{(r.max_drawdown * 100).toFixed(1)}%</td>
                <td>{r.total_trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
