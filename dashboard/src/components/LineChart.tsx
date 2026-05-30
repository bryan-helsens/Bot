// A dependency-free SVG line/area chart used by the equity and drawdown panels.

interface LineChartProps {
  values: number[];
  height?: number;
  color?: string;
  fill?: boolean;
  baseline?: number;
}

export function LineChart({
  values,
  height = 260,
  color = "var(--green)",
  fill = false,
  baseline,
}: LineChartProps) {
  if (values.length < 2) {
    return <div className="empty">Not enough data yet.</div>;
  }
  const width = 1000; // viewBox width; scales responsively
  const min = Math.min(...values, baseline ?? Infinity);
  const max = Math.max(...values, baseline ?? -Infinity);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const y = (v: number) => height - 10 - ((v - min) / span) * (height - 20);

  const points = values.map((v, i) => `${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`);
  const linePath = `M ${points.join(" L ")}`;
  const areaPath = `${linePath} L ${width},${height} L 0,${height} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ width: "100%", height }}
      role="img"
    >
      {baseline !== undefined && (
        <line
          x1={0}
          x2={width}
          y1={y(baseline)}
          y2={y(baseline)}
          stroke="var(--border)"
          strokeDasharray="4 4"
        />
      )}
      {fill && <path d={areaPath} fill={color} opacity={0.12} />}
      <path d={linePath} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}
