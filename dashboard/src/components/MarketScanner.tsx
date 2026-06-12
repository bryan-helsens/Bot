import { useState } from "react";
import { api } from "../api/client";
import { price as fmtPrice, pctRaw } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { ScannerRow } from "../types";

const SIGNAL_LABEL: Record<string, { text: string; cls: string }> = {
  oversold: { text: "OVERSOLD ↑buy", cls: "pos" },
  "dip-watch": { text: "dip watch", cls: "" },
  "trend-cross": { text: "TREND ↑", cls: "pos" },
  overbought: { text: "overbought", cls: "neg" },
  neutral: { text: "—", cls: "muted" },
};

/**
 * Live market scanner: every warmed-up coin with its RSI, EMA trend and a coarse
 * signal label. Sorted by RSI so the coins CLOSEST to an oversold entry float to
 * the top — this answers "why isn't it trading?" at a glance.
 */
export function MarketScanner() {
  const { data, refresh } = usePolling<ScannerRow[]>(() => api.scanner(), 5000);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const rows = (data ?? []).filter((r) =>
    r.symbol.toLowerCase().includes(filter.toLowerCase()),
  );

  async function act(symbol: string, fn: () => Promise<unknown>) {
    setBusy(symbol);
    try {
      await fn();
      await refresh();
    } catch {
      /* errors surface in Logs */
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <div className="log-head">
        <h2>Market Scanner ({rows.length})</h2>
        <input
          className="cap-input"
          placeholder="filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      {rows.length === 0 ? (
        <div className="empty">No coins warmed up yet (waiting for candle history)…</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Price</th>
              <th>RSI(14)</th>
              <th>EMA trend</th>
              <th>Gap</th>
              <th>Signal</th>
              <th>State</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const sig = SIGNAL_LABEL[r.signal] ?? SIGNAL_LABEL.neutral;
              return (
                <tr key={r.symbol}>
                  <td>{r.symbol}</td>
                  <td>{fmtPrice(r.price)}</td>
                  <td className={r.rsi != null && r.rsi < 40 ? "pos" : r.rsi != null && r.rsi > 70 ? "neg" : ""}>
                    {r.rsi ?? "—"}
                  </td>
                  <td className={r.trend === "up" ? "pos" : r.trend === "down" ? "neg" : ""}>
                    {r.trend ?? "—"}
                  </td>
                  <td className={(r.ema_gap_pct ?? 0) > 0 ? "pos" : (r.ema_gap_pct ?? 0) < 0 ? "neg" : ""}>
                    {pctRaw(r.ema_gap_pct, 2)}
                  </td>
                  <td className={sig.cls}>{sig.text}</td>
                  <td>
                    {r.has_position ? <span className="pos">● in trade</span> : null}
                    {r.muted ? <span className="muted"> muted</span> : null}
                  </td>
                  <td className="controls-row">
                    <button
                      className="btn-buy btn-sm"
                      disabled={busy === r.symbol}
                      onClick={() => act(r.symbol, () => api.testOrder(r.symbol, "buy"))}
                    >
                      Buy
                    </button>
                    <button
                      className="btn-sell btn-sm"
                      disabled={busy === r.symbol}
                      onClick={() => act(r.symbol, () => api.testOrder(r.symbol, "sell"))}
                    >
                      Sell
                    </button>
                    <button
                      className="btn btn-sm"
                      disabled={busy === r.symbol}
                      onClick={() =>
                        act(r.symbol, () => (r.muted ? api.unmute(r.symbol) : api.mute(r.symbol)))
                      }
                    >
                      {r.muted ? "Unmute" : "Mute"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="hint">
        Sorted by RSI (lowest first = closest to an oversold buy). <b>Buy/Sell</b> fire a
        manual order through the risk engine; <b>Mute</b> stops the bot opening NEW automated
        trades on that coin (manual still works). Refreshes every 5s.
      </p>
    </div>
  );
}
