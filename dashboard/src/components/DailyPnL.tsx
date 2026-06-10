import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { DailyPnlPoint } from "../types";
import { BarChart } from "./BarChart";

/** Realised PnL per day (green up / red down). */
export function DailyPnL() {
  const { data } = usePolling<DailyPnlPoint[]>(() => api.dailyPnl(), 15000);
  const bars = (data ?? []).map((d) => ({ label: d.date.slice(5), value: d.pnl }));

  return (
    <div className="panel">
      <h2>Daily PnL (realised)</h2>
      <BarChart bars={bars} signed />
    </div>
  );
}
