import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { SystemStatus, TradingStats } from "../types";

function age(s: number | null): string {
  if (s === null) return "—";
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function money(v: string): { text: string; cls: string } {
  const n = parseFloat(v);
  return {
    text: `${n >= 0 ? "+" : ""}${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
    cls: n > 0 ? "pos" : n < 0 ? "neg" : "",
  };
}

/** Health (is the bot alive?) + realised performance at a glance. */
export function Health() {
  const { data: status } = usePolling<SystemStatus>(() => api.systemStatus(), 4000);
  const { data: stats } = usePolling<TradingStats>(() => api.stats(), 5000);

  const candleStale = status?.candle_stale ?? false;
  const today = stats ? money(stats.today_pnl) : null;
  const week = stats ? money(stats.week_pnl) : null;

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
            <td className={today?.cls}>{today?.text ?? "—"} <span className="muted">({stats?.today_trades ?? 0} closed)</span></td>
          </tr>
          <tr>
            <th>PnL this week</th>
            <td className={week?.cls}>{week?.text ?? "—"}</td>
          </tr>
          <tr>
            <th>Win rate</th>
            <td>{stats ? `${(stats.win_rate * 100).toFixed(0)}% of ${stats.total_trades}` : "—"}</td>
          </tr>
          <tr>
            <th>Fees paid</th>
            <td className="muted">{stats ? parseFloat(stats.total_fees).toFixed(2) : "—"}</td>
          </tr>
          <tr>
            <th>Best / worst</th>
            <td>
              <span className="pos">+{stats ? parseFloat(stats.best_trade).toFixed(2) : "—"}</span>{" "}
              /{" "}
              <span className="neg">{stats ? parseFloat(stats.worst_trade).toFixed(2) : "—"}</span>
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
