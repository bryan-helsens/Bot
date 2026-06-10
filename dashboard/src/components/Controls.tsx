import { useState } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { SystemStatus } from "../types";

/** Engine controls: pause/resume new entries and a close-all panic button. */
export function Controls() {
  const { data: status, refresh } = usePolling<SystemStatus>(() => api.systemStatus(), 4000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run(fn: () => Promise<{ detail: string }>) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      setMsg(r.detail);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  const paused = status?.paused ?? false;
  const [amount, setAmount] = useState("");

  return (
    <div className="panel">
      <h2>Controls</h2>
      <div className="controls-row">
        {paused ? (
          <button className="btn-buy" disabled={busy} onClick={() => run(api.unpause)}>
            ▶ Resume entries
          </button>
        ) : (
          <button className="btn" disabled={busy} onClick={() => run(api.pause)}>
            ⏸ Pause entries
          </button>
        )}
        <button
          className="btn-sell"
          disabled={busy}
          onClick={() => {
            if (confirm("Close ALL open positions now?")) run(api.closeAll);
          }}
        >
          ⛔ Close all
        </button>
      </div>
      {paused && <div className="note err">Paused — managing existing positions, no new entries.</div>}

      <h2 style={{ marginTop: 16 }}>Capital (deposit / withdraw)</h2>
      <div className="controls-row">
        <input
          className="cap-input"
          type="number"
          placeholder="amount in USDT"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <button
          className="btn-buy"
          disabled={busy || !amount}
          onClick={() => run(() => api.adjustCapital(amount)).then(() => setAmount(""))}
        >
          + Deposit
        </button>
        <button
          className="btn"
          disabled={busy || !amount}
          onClick={() => run(() => api.adjustCapital("-" + amount.replace(/^-/, ""))).then(() => setAmount(""))}
        >
          − Withdraw
        </button>
      </div>

      {msg && <div className="note">{msg}</div>}
      <p className="hint">
        Pause stops NEW trades; existing keep their stops/TP. Use Capital AFTER you
        add/remove funds on the exchange — it is NOT counted as profit.
      </p>
    </div>
  );
}
