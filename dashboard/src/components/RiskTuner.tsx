import { useEffect, useState } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { Config } from "../types";

const FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "risk_per_trade", label: "Risk per trade", hint: "fraction of equity, e.g. 0.006 = 0.6%" },
  { key: "default_stop_loss_pct", label: "Stop-loss", hint: "fraction, e.g. 0.03 = 3%" },
  { key: "max_open_trades", label: "Max open trades", hint: "1–50" },
];

/** Live-tune core risk knobs. Effective on the next entry; not persisted. */
export function RiskTuner() {
  const { data: cfg } = usePolling<Config>(() => api.config(), 15000);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!cfg) return;
    setDraft({
      risk_per_trade: cfg.risk_per_trade,
      default_stop_loss_pct: cfg.default_stop_loss_pct,
      max_open_trades: String(cfg.max_open_trades),
    });
  }, [cfg?.risk_per_trade, cfg?.default_stop_loss_pct, cfg?.max_open_trades]);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.riskParams({
        risk_per_trade: draft.risk_per_trade,
        default_stop_loss_pct: draft.default_stop_loss_pct,
        max_open_trades: draft.max_open_trades,
      });
      setMsg({ ok: r.ok, text: r.detail });
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Risk Tuning</h2>
      <table>
        <tbody>
          {FIELDS.map((f) => (
            <tr key={f.key}>
              <th>{f.label}</th>
              <td>
                <input
                  className="cap-input"
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              </td>
              <td className="muted">{f.hint}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="controls-row" style={{ marginTop: 8 }}>
        <button className="btn-buy" disabled={busy} onClick={save}>
          Apply (live)
        </button>
      </div>
      {msg && <div className={msg.ok ? "note ok" : "note err"}>{msg.text}</div>}
      <p className="hint">
        Sizing reads these on every order, so changes apply to the next entry. Not written
        to <code>.env</code> — set <code>RISK__*</code> there to make them permanent.
      </p>
    </div>
  );
}
