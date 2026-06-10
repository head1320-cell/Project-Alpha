"use client";

import { useMemo } from "react";
import { Droplet, GitBranch } from "lucide-react";
import type { WaterfallStep } from "@/lib/realismData";

interface Props {
  steps: WaterfallStep[];
}

export default function ErosionWaterfall({ steps }: Props) {
  const { yMin, yMax, paddedMax, paddedMin } = useMemo(() => {
    const allVals = steps.flatMap((s) => [s.cumulative, s.cumulative - s.value]);
    const yMin = Math.min(0, ...allVals);
    const yMax = Math.max(...allVals);
    const range = yMax - yMin;
    return {
      yMin,
      yMax,
      paddedMin: yMin - range * 0.05,
      paddedMax: yMax + range * 0.1,
    };
  }, [steps]);

  const width = 800;
  const height = 380;
  const padding = { top: 40, right: 30, bottom: 70, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const stepX = chartW / steps.length;
  const barW = stepX * 0.55;

  const yScale = (v: number) =>
    padding.top + ((paddedMax - v) / (paddedMax - paddedMin)) * chartH;

  // Y-axis ticks
  const yTicks = useMemo(() => {
    const n = 5;
    return Array.from({ length: n + 1 }, (_, i) =>
      paddedMin + (i / n) * (paddedMax - paddedMin)
    );
  }, [paddedMin, paddedMax]);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-bold text-white tracking-wide uppercase flex items-center gap-2">
            <Droplet size={14} className="text-[#FF6B6B]" />
            Alpha Erosion Waterfall
          </h3>
          <p className="text-[10px] text-zinc-500 mt-1 font-mono">
            Ideal → 4 friction factors → Realistic outcome
          </p>
        </div>
        <div className="flex items-center gap-3 text-[9px] font-mono">
          <LegendItem color="#DAFFDE" label="Anchor" />
          <LegendItem color="#FF6B6B" label="Erosion" />
          <LegendItem color="#DEFF9A" label="Recovery" />
          <LegendItem color="#FFC857" label="Final" />
        </div>
      </div>

      {/* SVG Waterfall */}
      <div className="rounded-xl bg-[#0d0d0d] border border-zinc-800 p-5 overflow-x-auto">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-auto"
        >
          <defs>
            <linearGradient id="anchorGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#DAFFDE" stopOpacity="0.5" />
              <stop offset="100%" stopColor="#DAFFDE" stopOpacity="0.15" />
            </linearGradient>
            <linearGradient id="erosionGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FF6B6B" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#FF6B6B" stopOpacity="0.3" />
            </linearGradient>
            <linearGradient id="recoveryGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#DEFF9A" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#DEFF9A" stopOpacity="0.3" />
            </linearGradient>
            <linearGradient id="finalGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FFC857" stopOpacity="0.6" />
              <stop offset="100%" stopColor="#FFC857" stopOpacity="0.2" />
            </linearGradient>
            <filter id="glow">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Y-grid + labels */}
          {yTicks.map((tick, i) => {
            const y = yScale(tick);
            const isZero = Math.abs(tick) < 0.01;
            return (
              <g key={i}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={width - padding.right}
                  y2={y}
                  stroke={isZero ? "#3f3f46" : "#1a1a1a"}
                  strokeWidth={isZero ? "1" : "0.5"}
                  strokeDasharray={isZero ? "0" : "2 4"}
                />
                <text
                  x={padding.left - 8}
                  y={y + 3}
                  textAnchor="end"
                  fill="#52525b"
                  fontSize="9"
                  fontFamily="ui-monospace"
                >
                  {tick.toFixed(1)}%
                </text>
              </g>
            );
          })}

          {/* Title axis label */}
          <text
            x={padding.left}
            y={26}
            fill="#71717a"
            fontSize="9"
            fontFamily="ui-monospace"
            style={{ textTransform: "uppercase" }}
          >
            cumulative return path · {steps.length} stages
          </text>

          {/* Bars + connectors */}
          {steps.map((step, i) => {
            const cx = padding.left + i * stepX + stepX / 2;
            const barX = cx - barW / 2;
            const fromV = step.cumulative - step.value;
            const toV = step.cumulative;

            // Bar bounds
            let topV: number, botV: number;
            if (step.kind === "start" || step.kind === "end") {
              topV = Math.max(0, toV);
              botV = Math.min(0, toV);
            } else {
              topV = Math.max(fromV, toV);
              botV = Math.min(fromV, toV);
            }
            const barTop = yScale(topV);
            const barBot = yScale(botV);
            const barH = Math.max(2, barBot - barTop);

            // Gradient ID
            const gradId =
              step.kind === "start"    ? "anchorGrad" :
              step.kind === "end"      ? "finalGrad" :
              step.kind === "positive" ? "recoveryGrad" : "erosionGrad";
            const strokeColor =
              step.kind === "start"    ? "#DAFFDE" :
              step.kind === "end"      ? "#FFC857" :
              step.kind === "positive" ? "#DEFF9A" : "#FF6B6B";

            // Connector to next step
            const nextCx = i < steps.length - 1
              ? padding.left + (i + 1) * stepX + stepX / 2
              : null;

            return (
              <g key={i}>
                {/* Connector line (dotted) */}
                {nextCx !== null && step.kind !== "end" && (
                  <line
                    x1={barX + barW}
                    y1={yScale(toV)}
                    x2={nextCx - barW / 2}
                    y2={yScale(toV)}
                    stroke="#3f3f46"
                    strokeWidth="1"
                    strokeDasharray="2 3"
                  />
                )}

                {/* Bar */}
                <rect
                  x={barX}
                  y={barTop}
                  width={barW}
                  height={barH}
                  fill={`url(#${gradId})`}
                  stroke={strokeColor}
                  strokeWidth="1.5"
                  rx="3"
                  className="transition-all duration-500"
                />

                {/* Value label (top of bar) */}
                <text
                  x={cx}
                  y={step.value >= 0 ? barTop - 8 : barBot + 14}
                  textAnchor="middle"
                  fill={strokeColor}
                  fontSize="12"
                  fontWeight="700"
                  fontFamily="ui-monospace"
                  filter={step.kind === "end" || step.kind === "start" ? "url(#glow)" : undefined}
                >
                  {step.kind === "start" || step.kind === "end"
                    ? `+${step.value.toFixed(2)}%`
                    : `${step.value >= 0 ? "+" : ""}${step.value.toFixed(2)}%`}
                </text>

                {/* X-axis label */}
                <g transform={`translate(${cx}, ${height - padding.bottom + 16})`}>
                  <text
                    fill={step.kind === "end" ? "#FFC857" : step.kind === "start" ? "#DAFFDE" : "#a1a1aa"}
                    fontSize="10"
                    fontWeight={step.kind === "start" || step.kind === "end" ? "700" : "500"}
                    textAnchor="middle"
                  >
                    {step.label}
                  </text>
                  <text
                    y="14"
                    fill="#52525b"
                    fontSize="9"
                    fontFamily="ui-monospace"
                    textAnchor="middle"
                  >
                    Σ {step.cumulative.toFixed(2)}%
                  </text>
                </g>
              </g>
            );
          })}

          {/* Annotation arrow: Ideal → Realistic gap */}
          {steps.length >= 2 && (
            <g opacity="0.6">
              <line
                x1={padding.left + 0 * stepX + stepX / 2}
                y1={yScale(steps[0].cumulative) + 20}
                x2={padding.left + (steps.length - 1) * stepX + stepX / 2}
                y2={yScale(steps[steps.length - 1].cumulative) + 20}
                stroke="#52525b"
                strokeWidth="1"
                strokeDasharray="4 2"
                markerEnd="url(#arrowEnd)"
              />
            </g>
          )}
        </svg>
      </div>

      {/* Step details */}
      <div className="grid grid-cols-6 gap-2">
        {steps.map((step, i) => (
          <StepDetailCard key={i} step={step} />
        ))}
      </div>
    </div>
  );
}

function StepDetailCard({ step }: { step: WaterfallStep }) {
  const isPositive = step.value >= 0;
  const color =
    step.kind === "start"    ? "#DAFFDE" :
    step.kind === "end"      ? "#FFC857" :
    isPositive               ? "#DEFF9A" : "#FF6B6B";

  return (
    <div
      className="rounded-lg p-2 bg-[#0d0d0d] border border-zinc-800 hover:border-zinc-700 transition-colors"
    >
      <div className="text-[9px] uppercase text-zinc-500 font-bold tracking-wider truncate">
        {step.label}
      </div>
      <div className="text-base font-bold font-mono mt-1" style={{ color }}>
        {isPositive && step.kind !== "start" && step.kind !== "end" ? "+" : ""}
        {step.value.toFixed(2)}%
      </div>
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-2 h-2 rounded-sm" style={{ background: color }} />
      <span className="text-zinc-500 uppercase tracking-wider">{label}</span>
    </div>
  );
}
