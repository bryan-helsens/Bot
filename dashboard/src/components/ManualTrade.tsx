import { useState } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { SystemStatus } from "../types";

/**
 * Manual test order: fire a buy/sell through the full risk + execution path on
 * demand, instead of waiting for a strategy signal. Useful for verifying that
 * orders, positions, stops, PnL and the live dashboard all work end-to-end.
 */
export function ManualTrade() {
  const { data: status } = usePolling<SystemStatus>(() => api.systemStatus(), 10000);
  const symbols = status?.symbols ?? ["BTCUSDT"];
  const [symbol, setSymbol] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const chosen = symbol || symbols[0];

  async function send(side: "buy" | "sell") {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.testOrder(chosen, side);
      setMsg({ ok: r.ok, text: r.detail });
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Manual Test Order</h2>
      <div className="manual-trade">
        <select value={chosen} onChange={(e) => setSymbol(e.target.value)}>
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="btn-buy" disabled={busy} onClick={() => send("buy")}>
          Buy
        </button>
        <button className="btn-sell" disabled={busy} onClick={() => send("sell")}>
          Sell
        </button>
      </div>
      {msg && (
        <div className={msg.ok ? "note ok" : "note err"}>{msg.text}</div>
      )}
      <p className="hint">
        Buy opens a position; Sell closes it. Goes through the risk engine like a
        real order (testnet = fake money).
      </p>
    </div>
  );
}
