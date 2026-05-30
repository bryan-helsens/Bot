import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { EquityPoint } from "../types";
import { LineChart } from "./LineChart";

// Derive the drawdown series (as negative percentages) from the equity curve.
function drawdownSeries(values: number[]): number[] {
  let peak = -Infinity;
  return values.map((v) => {
    peak = Math.max(peak, v);
    return peak > 0 ? -((peak - v) / peak) * 100 : 0;
  });
}

export function DrawdownChart() {
  const { data, error } = usePolling<EquityPoint[]>(() => api.equityCurve(), 10000);
  const dd = drawdownSeries((data ?? []).map((p) => p.equity));

  return (
    <div className="panel">
      <h2>Drawdown (%)</h2>
      {error && <div className="error">{error}</div>}
      <LineChart values={dd} height={200} color="var(--red)" fill baseline={0} />
    </div>
  );
}
