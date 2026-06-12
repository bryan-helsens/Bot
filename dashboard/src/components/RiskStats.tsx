import { useState } from "react";
import { api } from "../api/client";
import { cls, pct, signedMoney } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { RiskStatus } from "../types";

export function RiskStats() {
  const { data, error, refresh } = usePolling<RiskStatus>(() => api.riskStatus(), 5000);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>Risk</h2>
      {error && <div className="error">{error}</div>}
      {data && (
        <>
          <table>
            <tbody>
              <tr>
                <th>Emergency Shutdown</th>
                <td className={data.emergency_shutdown ? "neg" : "pos"}>
                  {data.emergency_shutdown ? `ON — ${data.emergency_reason}` : "off"}
                </td>
              </tr>
              <tr>
                <th>Circuit Breaker</th>
                <td className={data.circuit_breaker_active ? "neg" : "pos"}>
                  {data.circuit_breaker_active
                    ? `tripped (${Math.round(data.circuit_breaker_cooldown)}s)`
                    : "ok"}
                </td>
              </tr>
              <tr>
                <th>Daily PnL</th>
                <td className={cls(data.daily_pnl)}>{signedMoney(data.daily_pnl)}</td>
              </tr>
              <tr>
                <th>Weekly PnL</th>
                <td className={cls(data.weekly_pnl)}>{signedMoney(data.weekly_pnl)}</td>
              </tr>
              <tr>
                <th>Drawdown</th>
                <td className="neg">{pct(data.current_drawdown)}</td>
              </tr>
              <tr>
                <th>Open Trades</th>
                <td>
                  {data.open_trades} / {data.max_open_trades}
                </td>
              </tr>
            </tbody>
          </table>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button
              className="btn danger"
              disabled={busy}
              onClick={() => act(api.emergencyStop)}
            >
              Emergency Stop
            </button>
            <button className="btn" disabled={busy} onClick={() => act(api.resume)}>
              Resume
            </button>
          </div>
        </>
      )}
    </div>
  );
}
