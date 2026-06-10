import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { LogEntry } from "../types";

/** Live buy/sell feed — one clear line per entry, exit or partial take-profit. */
export function ActivityFeed() {
  const { data } = usePolling<LogEntry[]>(() => api.activity(50), 2000);
  const rows = data ? [...data].reverse() : []; // newest first

  return (
    <div className="panel">
      <h2>Activity (buys & sells)</h2>
      {rows.length === 0 ? (
        <div className="empty">No buys or sells yet.</div>
      ) : (
        <div className="activity-box">
          {rows.map((e, i) => (
            <ActivityLine key={i} entry={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function ActivityLine({ entry }: { entry: LogEntry }) {
  const d = entry.data;
  const time = entry.ts ? entry.ts.slice(11, 19) : "";
  let kind = "";
  let cls = "";
  let text = "";

  if (entry.event === "position_opened") {
    kind = "BUY";
    cls = "act-buy";
    text = `${d.symbol} ${num(d.qty)} @ ${num(d.entry)}`;
  } else if (entry.event === "position_closed") {
    kind = "SELL";
    cls = "act-sell";
    const pnl = parseFloat(d.net_pnl ?? "0");
    text = `${d.symbol} @ ${num(d.exit)} · pnl ${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} · ${d.reason ?? ""}`;
  } else if (entry.event === "position_reduced") {
    kind = "TP";
    cls = "act-tp";
    const pnl = parseFloat(d.net_pnl ?? "0");
    text = `${d.symbol} ${num(d.qty)} · pnl ${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}`;
  } else if (entry.event === "capital_adjusted") {
    const amt = parseFloat(d.amount ?? "0");
    kind = amt >= 0 ? "DEP" : "WD";
    cls = "act-cap";
    text = `${amt >= 0 ? "💰 deposit +" : "💸 withdraw "}${num(d.amount)} · cash ${num(d.cash)}`;
  } else {
    text = entry.event;
  }

  return (
    <div className="act-line">
      <span className="act-time">{time}</span>
      <span className={`act-kind ${cls}`}>{kind}</span>
      <span className="act-text">{text}</span>
    </div>
  );
}

function num(v: string | undefined): string {
  if (v === undefined) return "—";
  const n = parseFloat(v);
  if (!isFinite(n)) return v;
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}
