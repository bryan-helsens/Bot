import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { EquityPoint } from "../types";
import { LineChart } from "./LineChart";

export function EquityCurve() {
  const { data, error } = usePolling<EquityPoint[]>(() => api.equityCurve(), 10000);
  const values = (data ?? []).map((p) => p.equity);

  return (
    <div className="panel">
      <h2>Equity Curve</h2>
      {error && <div className="error">{error}</div>}
      <LineChart values={values} color="var(--green)" fill baseline={values[0]} />
    </div>
  );
}
