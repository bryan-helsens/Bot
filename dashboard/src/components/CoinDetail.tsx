import { useState } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { CoinDetail as Detail, SystemStatus } from "../types";
import { PriceChart } from "./PriceChart";

function rsiClass(rsi: number | null): string {
  if (rsi === null) return "";
  if (rsi < 35) return "pos"; // oversold -> buy zone
  if (rsi > 70) return "neg"; // overbought
  return "";
}

const n = (v: string | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : parseFloat(v).toLocaleString(undefined, { maximumFractionDigits: 6, minimumFractionDigits: d });

function cls(v: string | number) {
  const x = typeof v === "string" ? parseFloat(v) : v;
  return x > 0 ? "pos" : x < 0 ? "neg" : "";
}

/** Per-coin detail: current position + full trade history + stats for one coin. */
export function CoinDetail() {
  const { data: status } = usePolling<SystemStatus>(() => api.systemStatus(), 10000);
  const symbols = status?.symbols ?? [];
  const [symbol, setSymbol] = useState("");
  const chosen = symbol || symbols[0] || "BTCUSDT";
  const { data } = usePolling<Detail>(() => api.coinDetail(chosen), 5000, [chosen]);

  return (
    <div className="panel">
      <div className="log-head">
        <h2>Coin detail</h2>
        <select value={chosen} onChange={(e) => setSymbol(e.target.value)} className="cap-input" style={{ width: 160 }}>
          {symbols.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {!data ? (
        <div className="empty">…</div>
      ) : (
        <>
          <div style={{ marginBottom: 12 }}>
            <div className="coin-rsi">
              RSI(14){data.price_timeframe ? ` · ${data.price_timeframe}` : ""}:{" "}
              <span className={`value ${rsiClass(data.rsi)}`}>
                {data.rsi === null ? "—" : data.rsi.toFixed(1)}
              </span>
              <span className="muted"> (buy &lt;35 · sell &gt;70)</span>
            </div>
            <PriceChart
              prices={data.prices}
              refs={[
                ...(data.has_position && data.entry_price
                  ? [{ value: parseFloat(data.entry_price), color: "var(--green, #3ddc84)", label: "entry" }]
                  : []),
                ...(data.has_position && data.stop_loss
                  ? [{ value: parseFloat(data.stop_loss), color: "var(--red)", label: "stop" }]
                  : []),
              ]}
            />
          </div>
          <table>
            <tbody>
              <tr><th>Open position</th><td>
                {data.has_position
                  ? `${data.side} ${n(data.quantity)} · $${n(data.value)} · entry ${n(data.entry_price)} · mark ${n(data.mark_price)}`
                  : "none"}
              </td></tr>
              {data.has_position && (
                <tr><th>Unrealised PnL</th><td className={cls(data.unrealized_pnl)}>{n(data.unrealized_pnl)} · stop {n(data.stop_loss)}</td></tr>
              )}
              <tr><th>Realised PnL (all time)</th><td className={cls(data.realized_pnl)}>{n(data.realized_pnl)}</td></tr>
              <tr><th>Trades · win-rate · fees</th><td>{data.trade_count} · {(data.win_rate * 100).toFixed(0)}% · {n(data.total_fees)}</td></tr>
            </tbody>
          </table>

          <h2 style={{ marginTop: 14 }}>Trade history — {chosen}</h2>
          {data.trades.length === 0 ? (
            <div className="empty">No closed trades for this coin yet.</div>
          ) : (
            <table>
              <thead>
                <tr><th>Closed</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>PnL</th><th>%</th><th>Reason</th></tr>
              </thead>
              <tbody>
                {data.trades.map((t) => (
                  <tr key={t.id}>
                    <td className="muted">{t.closed_at.slice(5, 16).replace("T", " ")}</td>
                    <td className={t.side === "long" ? "pos" : "neg"}>{t.side}</td>
                    <td>{n(t.quantity)}</td>
                    <td>{n(t.entry_price)}</td>
                    <td>{n(t.exit_price)}</td>
                    <td className={cls(t.net_pnl)}>{n(t.net_pnl)}</td>
                    <td className={cls(t.return_pct)}>{(parseFloat(t.return_pct) * 100).toFixed(2)}%</td>
                    <td className="muted">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
