// Dependency-free SVG bar chart. Bars are coloured per-value when `signed` (green
// for >=0, red for <0), else a single accent colour.

interface Bar {
  label: string;
  value: number;
}

export function BarChart({
  bars,
  height = 220,
  signed = false,
  color = "var(--accent)",
}: {
  bars: Bar[];
  height?: number;
  signed?: boolean;
  color?: string;
}) {
  if (bars.length === 0) return <div className="empty">No data yet.</div>;

  const width = 1000;
  const max = Math.max(1e-9, ...bars.map((b) => Math.abs(b.value)));
  const n = bars.length;
  const gap = 4;
  const bw = (width - gap * (n + 1)) / n;
  const zeroY = signed ? height / 2 : height - 18;
  const scale = signed ? (height / 2 - 8) / max : (height - 28) / max;

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }} role="img">
        {signed && <line x1={0} x2={width} y1={zeroY} y2={zeroY} stroke="var(--border)" />}
        {bars.map((b, i) => {
          const h = Math.abs(b.value) * scale;
          const x = gap + i * (bw + gap);
          const y = b.value >= 0 ? zeroY - h : zeroY;
          const fill = signed ? (b.value >= 0 ? "var(--green, #3ddc84)" : "var(--red)") : color;
          return <rect key={i} x={x} y={y} width={bw} height={Math.max(1, h)} fill={fill} rx={2} />;
        })}
      </svg>
      <div className="bar-labels" style={{ display: "flex", gap: `${gap}px`, padding: "0 4px" }}>
        {bars.map((b, i) => (
          <span key={i} style={{ flex: 1, textAlign: "center" }} className="muted">
            {bars.length <= 16 ? b.label : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
