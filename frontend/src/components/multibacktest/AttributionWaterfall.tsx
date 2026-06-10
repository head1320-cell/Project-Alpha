"use client";

interface WaterfallStep {
  step: string;
  label: string;
  value: number;
  running_total: number;
  kind: "baseline" | "positive" | "negative" | "interaction" | "total";
}

interface Props {
  waterfall: WaterfallStep[];
  height?: number;
}

const COLORS = {
  baseline:    "#6b7fa3",
  positive:    "#69f0ae",
  negative:    "#ff5252",
  interaction: "#e040fb",
  total:       "#00e5ff",
};

export default function AttributionWaterfall({ waterfall, height = 320 }: Props) {
  if (!waterfall || waterfall.length === 0) {
    return (
      <div style={{
        padding: 32, textAlign: "center", color: "#6b7fa3", fontSize: 12,
      }}>
        Attribution 데이터 없음
      </div>
    );
  }

  const n = waterfall.length;
  const padding = { top: 30, right: 40, bottom: 50, left: 70 };
  const width = Math.max(600, n * 90);

  // Y축 범위
  const allValues = waterfall.flatMap((w) => [w.running_total, w.running_total - w.value]);
  let yMin = Math.min(0, ...allValues);
  let yMax = Math.max(...allValues);
  const range = yMax - yMin;
  yMin -= range * 0.1;
  yMax += range * 0.1;

  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const barWidth = (chartWidth / n) * 0.6;
  const stepX = chartWidth / n;

  const yScale = (v: number) => padding.top + (yMax - v) / (yMax - yMin) * chartHeight;
  const zeroY = yScale(0);

  // Y축 tick (5개)
  const yTicks = Array.from({ length: 5 }, (_, i) =>
    yMin + (i / 4) * (yMax - yMin)
  );

  return (
    <div style={{ overflowX: "auto" }}>
      <svg width={width} height={height}
            viewBox={`0 0 ${width} ${height}`}
            xmlns="http://www.w3.org/2000/svg">

        {/* Y-axis grid + labels */}
        {yTicks.map((tick, i) => {
          const y = yScale(tick);
          return (
            <g key={i}>
              <line x1={padding.left} y1={y}
                     x2={width - padding.right} y2={y}
                     stroke="#1e2d4a" strokeWidth="0.5"
                     strokeDasharray={tick === 0 ? "0" : "2 4"} />
              <text x={padding.left - 8} y={y + 3}
                     fill="#6b7fa3" fontSize="10" textAnchor="end"
                     fontFamily="'Roboto Mono', monospace">
                {tick.toFixed(1)}%
              </text>
            </g>
          );
        })}

        {/* Zero baseline */}
        <line x1={padding.left} y1={zeroY}
               x2={width - padding.right} y2={zeroY}
               stroke="#3a4f7a" strokeWidth="1" />

        {/* Bars */}
        {waterfall.map((step, i) => {
          const cx = padding.left + i * stepX + stepX / 2;
          const barX = cx - barWidth / 2;
          const fromValue = step.running_total - step.value;
          const toValue = step.running_total;

          let barTop, barBottom;
          if (step.kind === "baseline" || step.kind === "total") {
            barTop = yScale(Math.max(0, toValue));
            barBottom = yScale(Math.min(0, toValue));
          } else {
            barTop = yScale(Math.max(fromValue, toValue));
            barBottom = yScale(Math.min(fromValue, toValue));
          }

          const color = COLORS[step.kind];
          const barHeight = Math.max(2, barBottom - barTop);

          // Connecting line (이전 step의 running_total에서)
          let connector = null;
          if (i > 0 && step.kind !== "total") {
            const prevX = padding.left + (i - 1) * stepX + stepX / 2 + barWidth / 2;
            const yConn = yScale(fromValue);
            connector = (
              <line x1={prevX} y1={yConn} x2={barX} y2={yConn}
                     stroke="#6b7fa3" strokeWidth="1"
                     strokeDasharray="3 3" />
            );
          }

          return (
            <g key={i}>
              {connector}
              <rect x={barX} y={barTop}
                     width={barWidth} height={barHeight}
                     fill={color}
                     fillOpacity={step.kind === "total" || step.kind === "baseline" ? 0.7 : 0.85}
                     stroke={color} strokeWidth="1.5"
                     rx="2" />

              {/* Value 라벨 (바 위/아래) */}
              <text x={cx} y={step.value >= 0 ? barTop - 6 : barBottom + 14}
                     fill={color} fontSize="11" textAnchor="middle"
                     fontWeight="700" fontFamily="'Roboto Mono', monospace">
                {step.value >= 0 ? "+" : ""}{step.value.toFixed(2)}%
              </text>

              {/* X축 라벨 */}
              <g transform={`translate(${cx}, ${height - padding.bottom + 10})`}>
                <text fill="#a7c8ff" fontSize="10" textAnchor="middle"
                       transform="rotate(-20)"
                       fontWeight={step.kind === "total" ? 700 : 500}>
                  {step.label}
                </text>
              </g>
            </g>
          );
        })}

        {/* Title */}
        <text x={padding.left} y={20}
               fill="#a7c8ff" fontSize="11" fontWeight="600">
          5-Factor Attribution — 베이스라인부터 최종 수익까지의 단계별 기여
        </text>
      </svg>
    </div>
  );
}
