import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { Config } from "../types";

const pct = (v: string) => `${(parseFloat(v) * 100).toFixed(2)}%`;

/** Read-only view of the active risk + universe config (what's actually running). */
export function ConfigPanel() {
  const { data: c } = usePolling<Config>(() => api.config(), 15000);
  if (!c) return <div className="panel"><h2>Active config</h2><div className="empty">…</div></div>;

  const rows: [string, string][] = [
    ["Sizing", `${c.sizing_method} · ${pct(c.risk_per_trade)} per trade`],
    ["Stop-loss", pct(c.default_stop_loss_pct)],
    ["Trailing stop", pct(c.trailing_stop_pct)],
    ["Take-profit", c.take_profit_levels.join(", ") || "—"],
    ["Max open / coin cap", `${c.max_open_trades} · ${pct(c.max_exposure_per_coin)}`],
    ["Portfolio exposure cap", pct(c.max_portfolio_exposure)],
    ["Daily loss / drawdown halt", `${pct(c.max_daily_loss)} · ${pct(c.max_drawdown)}`],
    ["Min consensus", String(c.min_consensus)],
    ["Timeframes", c.timeframes.join(", ")],
    ["Symbols", `${c.symbols.length}: ${c.symbols.join(", ")}`],
  ];

  return (
    <div className="panel">
      <h2>Active config</h2>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
