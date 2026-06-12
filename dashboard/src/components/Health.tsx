import { api } from "../api/client";
import { ago as age, cls, money, signedMoney } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { SystemStatus, TradingStats } from "../types";

/** Health (is the bot alive?) + realised performance at a glance. */
export function Health() {
  const { data: status } = usePolling<SystemStatus>(() => api.systemStatus(), 4000);
  const { data: stats } = usePolling<TradingStats>(() => api.stats(), 5000);

  const candleStale = status?.candle_stale ?? false;

  return (
    <div className="panel">
      <h2>Health &amp; performance</h2>
      <table>
        <tbody>
          <tr>
            <th>Last candle</th>
            <td className={candleStale ? "neg" : "pos"}>{age(status?.last_candle_age ?? null)}</td>
          </tr>
          <tr>
            <th>Last entry/exit</th>
            <td>{age(status?.last_trade_age ?? null)}</td>
          </tr>
          <tr>
            <th>Open positions</th>
            <td>{status?.open_positions ?? 0}</td>
          </tr>
          <tr>
            <th>Live streams</th>
            <td>{status?.active_streams ?? 0}</td>
          </tr>
          <tr>
            <th>PnL today (closed)</th>
            <td className={stats ? cls(stats.today_pnl) : ""}>
              {stats ? signedMoney(stats.today_pnl) : "—"}{" "}
              <span className="muted">({stats?.today_trades ?? 0} closed)</span>
            </td>
          </tr>
          <tr>
            <th>PnL this week</th>
            <td className={stats ? cls(stats.week_pnl) : ""}>
              {stats ? signedMoney(stats.week_pnl) : "—"}
            </td>
          </tr>
          <tr>
            <th>Win rate</th>
            <td>{stats ? `${(stats.win_rate * 100).toFixed(0)}% of ${stats.total_trades}` : "—"}</td>
          </tr>
          <tr>
            <th>Fees paid</th>
            <td className="muted">{stats ? money(stats.total_fees) : "—"}</td>
          </tr>
          <tr>
            <th>Best / worst</th>
            <td>
              <span className="pos">{stats ? signedMoney(stats.best_trade) : "—"}</span>{" "}
              /{" "}
              <span className="neg">{stats ? signedMoney(stats.worst_trade) : "—"}</span>
            </td>
          </tr>
        </tbody>
      </table>
      {candleStale && status?.running && (
        <div className="note err">⚠️ No fresh candle recently — check the data stream.</div>
      )}
    </div>
  );
}
