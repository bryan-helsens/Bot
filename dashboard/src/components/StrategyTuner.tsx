import { useEffect, useState } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { StrategyInfo } from "../types";

function StrategyCard({ s, onSaved }: { s: StrategyInfo; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Seed the editable draft from the live params once (and when they change names).
  useEffect(() => {
    setDraft(
      Object.fromEntries(Object.entries(s.params).map(([k, v]) => [k, String(v)])),
    );
  }, [s.name, Object.keys(s.params).join(",")]);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      // Only send changed keys.
      const changed: Record<string, string> = {};
      for (const [k, v] of Object.entries(draft)) {
        if (String(s.params[k]) !== v) changed[k] = v;
      }
      if (Object.keys(changed).length === 0) {
        setMsg({ ok: false, text: "Nothing changed." });
        return;
      }
      const r = await api.updateStrategyParams(s.name, changed);
      setMsg({ ok: r.ok, text: r.detail });
      if (r.ok) onSaved();
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>
        {s.name} <span className="muted">({s.class})</span>
      </h2>
      <table>
        <tbody>
          {Object.keys(s.params).map((k) => (
            <tr key={k}>
              <th>{k}</th>
              <td>
                <input
                  className="cap-input"
                  value={draft[k] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                />
              </td>
              <td className="muted">default {String(s.default_params[k] ?? "—")}</td>
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
    </div>
  );
}

/** Live strategy-parameter tuning — effective next candle, not persisted to file. */
export function StrategyTuner() {
  const { data, refresh } = usePolling<StrategyInfo[]>(() => api.strategies(), 15000);
  const strategies = data ?? [];

  return (
    <>
      {strategies.length === 0 ? (
        <div className="panel">
          <h2>Strategy Tuning</h2>
          <div className="empty">No strategies loaded (needs the live engine).</div>
        </div>
      ) : (
        strategies.map((s) => <StrategyCard key={s.name} s={s} onSaved={refresh} />)
      )}
      <p className="hint">
        Changes take effect on the next candle and are <b>not</b> written to your config
        file — edit <code>config/strategies.yaml</code> to make them permanent. Use this to
        experiment quickly (e.g. raise <code>oversold</code> for more entries).
      </p>
    </>
  );
}
