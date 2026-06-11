// Small price line chart with optional horizontal reference lines (entry / stop),
// so you can see where the current position sits relative to the price.

interface RefLine {
  value: number;
  color: string;
  label: string;
}

export function PriceChart({
  prices,
  refs = [],
  height = 180,
}: {
  prices: number[];
  refs?: RefLine[];
  height?: number;
}) {
  if (prices.length < 2) return <div className="empty">No price data yet.</div>;

  const width = 1000;
  const refVals = refs.map((r) => r.value).filter((v) => v > 0);
  const min = Math.min(...prices, ...refVals);
  const max = Math.max(...prices, ...refVals);
  const span = max - min || 1;
  const stepX = width / (prices.length - 1);
  const y = (v: number) => height - 8 - ((v - min) / span) * (height - 16);
  const path = `M ${prices.map((v, i) => `${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join(" L ")}`;
  const up = prices[prices.length - 1] >= prices[0];

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }} role="img">
        {refs.map((r, i) =>
          r.value > 0 ? (
            <line key={i} x1={0} x2={width} y1={y(r.value)} y2={y(r.value)} stroke={r.color} strokeDasharray="5 4" strokeWidth={1} />
          ) : null,
        )}
        <path d={path} fill="none" stroke={up ? "var(--green, #3ddc84)" : "var(--red)"} strokeWidth={2} />
      </svg>
      <div className="chart-legend">
        {refs.map((r, i) => (
          <span key={i} style={{ color: r.color }}>● {r.label} {r.value > 0 ? r.value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : "—"}</span>
        ))}
      </div>
    </div>
  );
}
