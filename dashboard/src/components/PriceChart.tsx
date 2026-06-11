// Small price line chart with optional horizontal reference lines (entry / stop),
// so you can see where the current position sits relative to the price.

interface RefLine {
  value: number;
  color: string;
  label: string;
}

export interface Marker {
  index: number; // x position on the price series
  value: number; // price (y)
  color: string;
  buy: boolean;
}

export function PriceChart({
  prices,
  refs = [],
  markers = [],
  height = 180,
}: {
  prices: number[];
  refs?: RefLine[];
  markers?: Marker[];
  height?: number;
}) {
  if (prices.length < 2) return <div className="empty">No price data yet.</div>;

  const width = 1000;
  const refVals = refs.map((r) => r.value).filter((v) => v > 0);
  const mVals = markers.map((m) => m.value);
  const min = Math.min(...prices, ...refVals, ...mVals);
  const max = Math.max(...prices, ...refVals, ...mVals);
  const span = max - min || 1;
  const stepX = width / (prices.length - 1);
  const x = (i: number) => Math.max(0, Math.min(prices.length - 1, i)) * stepX;
  const y = (v: number) => height - 8 - ((v - min) / span) * (height - 16);
  const path = `M ${prices.map((v, i) => `${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join(" L ")}`;
  const up = prices[prices.length - 1] >= prices[0];

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }} role="img">
        {refs.map((r, i) =>
          r.value > 0 ? (
            <line key={`r${i}`} x1={0} x2={width} y1={y(r.value)} y2={y(r.value)} stroke={r.color} strokeDasharray="5 4" strokeWidth={1} />
          ) : null,
        )}
        <path d={path} fill="none" stroke={up ? "var(--green, #3ddc84)" : "var(--red)"} strokeWidth={2} />
        {markers.map((m, i) => (
          <g key={`m${i}`}>
            <circle cx={x(m.index)} cy={y(m.value)} r={6} fill={m.color} stroke="#000" strokeWidth={0.5} />
            <text x={x(m.index)} y={y(m.value) + 3.5} textAnchor="middle" fontSize={8} fill="#000" fontWeight="700">
              {m.buy ? "B" : "S"}
            </text>
          </g>
        ))}
      </svg>
      <div className="chart-legend">
        {refs.map((r, i) => (
          <span key={i} style={{ color: r.color }}>● {r.label} {r.value > 0 ? r.value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : "—"}</span>
        ))}
        {markers.length > 0 && (
          <>
            <span style={{ color: "var(--green, #3ddc84)" }}>● B = buy</span>
            <span style={{ color: "var(--red)" }}>● S = sell</span>
          </>
        )}
      </div>
    </div>
  );
}
