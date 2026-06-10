import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import { BarChart } from "./BarChart";

/** Current capital allocation per coin (% of equity), largest first. */
export function Allocation() {
  const { data } = usePolling<Record<string, number>>(() => api.allocation(), 5000);
  const bars = Object.entries(data ?? {})
    .map(([sym, frac]) => ({ label: sym.replace("USDT", ""), value: frac * 100 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 16);

  return (
    <div className="panel">
      <h2>Allocation (% of equity)</h2>
      {bars.length === 0 ? (
        <div className="empty">No open positions.</div>
      ) : (
        <BarChart bars={bars} color="var(--accent)" height={200} />
      )}
    </div>
  );
}
