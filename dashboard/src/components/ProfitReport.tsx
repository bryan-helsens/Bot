import { useState } from "react";
import { api } from "../api/client";
import { cls, holdTime, money, pctRaw, signedMoney } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Report } from "../types";

const WINDOWS = [7, 30, 90];

/**
 * Honest go/no-go report: realised results AFTER fees, next to a buy & hold BTC
 * benchmark — so the decision to ever risk real money rests on evidence.
 */
export function ProfitReport() {
  const [days, setDays] = useState(7);
  const { data } = usePolling<Report>(() => api.report(days), 15000, [days]);

  if (!data) {
    return (
      <div className="panel">
        <h2>Profitability Report</h2>
        <div className="empty">Loading…</div>
      </div>
    );
  }

  const verdictCls =
    data.trades === 0 ? "" : parseFloat(data.net_pnl) > 0 ? "pos" : "neg";

  const rows: { label: string; value: string; cls?: string }[] = [
    { label: "Closed trades", value: String(data.trades) },
    { label: "Net PnL (after fees)", value: signedMoney(data.net_pnl), cls: cls(data.net_pnl) },
    { label: "Bot return", value: pctRaw(data.bot_return_pct, 2), cls: data.bot_return_pct >= 0 ? "pos" : "neg" },
    {
      label: "Buy & hold BTC",
      value: data.benchmark_pct == null ? "—" : pctRaw(data.benchmark_pct, 2),
      cls: (data.benchmark_pct ?? 0) >= 0 ? "pos" : "neg",
    },
    { label: "Win rate", value: pctRaw(data.win_rate * 100) },
    {
      label: "Profit factor",
      value: data.profit_factor.toFixed(2),
      cls: data.profit_factor >= 1 ? "pos" : "neg",
    },
    { label: "Expectancy / trade", value: signedMoney(data.expectancy), cls: cls(data.expectancy) },
    { label: "Fees paid", value: money(data.fees), cls: "muted" },
    {
      label: "Fees % of gross profit",
      value: data.fees_pct_of_gross == null ? "—" : pctRaw(data.fees_pct_of_gross),
      cls: (data.fees_pct_of_gross ?? 0) > 50 ? "neg" : "",
    },
    { label: "Avg hold time", value: holdTime(data.avg_hold_seconds) },
  ];

  return (
    <div className="panel">
      <div className="log-head">
        <h2>Profitability Report</h2>
        <div className="controls-row">
          {WINDOWS.map((w) => (
            <button
              key={w}
              className={`btn btn-sm ${days === w ? "active" : ""}`}
              onClick={() => setDays(w)}
            >
              {w}d
            </button>
          ))}
        </div>
      </div>
      <div className={`note ${verdictCls === "neg" ? "err" : "ok"}`}>{data.verdict}</div>
      <div className="grid">
        {rows.map((r) => (
          <div className="col-4 stat" key={r.label}>
            <span className="label">{r.label}</span>
            <span className={`value ${r.cls ?? ""}`}>{r.value}</span>
          </div>
        ))}
      </div>
      <p className="hint">
        Benchmark = holding BTC over the data window the bot has in memory. "Beating" it means
        your strategy added value beyond just being long crypto. Fees as a big share of gross
        profit is a red flag for over-trading.
      </p>
    </div>
  );
}
