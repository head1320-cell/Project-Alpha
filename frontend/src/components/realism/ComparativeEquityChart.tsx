"use client";

import { useMemo } from "react";
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceArea, Legend,
} from "recharts";
import { TrendingUp, Sparkles, Zap } from "lucide-react";
import type { BacktestResult } from "@/lib/realismData";

const REGIME_BG: Record<string, string> = {
  GOLDILOCKS:  "rgba(222,255,154,0.04)",
  REFLATION:   "rgba(255,200,87,0.04)",
  STAGFLATION: "rgba(255,107,107,0.05)",
  DEFLATION:   "rgba(66,165,245,0.04)",
};

const REGIME_LABEL: Record<string, { color: string; label: string }> = {
  GOLDILOCKS:  { color: "#DEFF9A", label: "Goldilocks" },
  REFLATION:   { color: "#FFC857", label: "Reflation" },
  STAGFLATION: { color: "#FF6B6B", label: "Stagflation" },
  DEFLATION:   { color: "#7DD3FC", label: "Deflation" },
};

interface Props {
  ideal: BacktestResult;
  reality: BacktestResult;
  mode: "ideal" | "reality";
  maxPoints?: number;
}

export default function ComparativeEquityChart({
  ideal, reality, mode, maxPoints = 250,
}: Props) {
  // Merged chart data
  const { chartData, regimeBands } = useMemo(() => {
    const n = ideal.daily_records.length;
    const step = Math.max(1, Math.floor(n / maxPoints));

    const data = [];
    for (let i = 0; i < n; i += step) {
      const idR = ideal.daily_records[i];
      const rlR = reality.daily_records[i];
      data.push({
        date:      idR.date,
        shortDate: idR.date.slice(5),
        ideal:     idR.cumulative_return,
        reality:   rlR.cumulative_return,
        gap:       idR.cumulative_return - rlR.cumulative_return,
        regime:    idR.regime,
      });
    }

    // Regime bands
    const bands: { startIdx: number; endIdx: number; regime: string }[] = [];
    let cur = data[0]?.regime;
    let startIdx = 0;
    for (let i = 1; i < data.length; i++) {
      if (data[i].regime !== cur) {
        if (cur) bands.push({ startIdx, endIdx: i - 1, regime: cur });
        cur = data[i].regime;
        startIdx = i;
      }
    }
    if (cur) bands.push({ startIdx, endIdx: data.length - 1, regime: cur });

    return { chartData: data, regimeBands: bands };
  }, [ideal, reality, maxPoints]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-bold text-white tracking-wide uppercase flex items-center gap-2">
            <TrendingUp size={14} className="text-[#DEFF9A]" />
            Equity Curves · Ideal vs Reality
          </h3>
          <p className="text-[10px] text-zinc-500 mt-1 font-mono">
            {chartData.length} points · Regime bands overlay
          </p>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 text-[10px]">
          <div className="flex items-center gap-2">
            <svg width="24" height="2"><line x1="0" y1="1" x2="24" y2="1" stroke="#DAFFDE" strokeWidth="2" strokeDasharray="4 3" /></svg>
            <Sparkles size={10} className="text-[#DAFFDE]" />
            <span className="text-zinc-400 font-medium">Ideal (Stage 11)</span>
          </div>
          <div className="flex items-center gap-2">
            <svg width="24" height="3"><line x1="0" y1="1.5" x2="24" y2="1.5" stroke="#DEFF9A" strokeWidth="2.5" /></svg>
            <Zap size={10} className="text-[#DEFF9A]" />
            <span className="text-white font-bold">Reality (Stage 12)</span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="rounded-xl bg-[#0d0d0d] border border-zinc-800 p-4">
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 20 }}>
            <defs>
              <linearGradient id="realityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor="#DEFF9A" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#DEFF9A" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="gapFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor="#FF6B6B" stopOpacity={0.15} />
                <stop offset="100%" stopColor="#FF6B6B" stopOpacity={0.02} />
              </linearGradient>
            </defs>

            {/* Regime band backgrounds */}
            {regimeBands.map((band, i) => (
              <ReferenceArea
                key={i}
                x1={chartData[band.startIdx]?.shortDate}
                x2={chartData[band.endIdx]?.shortDate}
                fill={REGIME_BG[band.regime] || "transparent"}
                fillOpacity={1}
                ifOverflow="visible"
              />
            ))}

            <CartesianGrid strokeDasharray="2 4" stroke="#1f1f1f" />
            <XAxis
              dataKey="shortDate"
              tick={{ fill: "#52525b", fontSize: 9, fontFamily: "ui-monospace" }}
              stroke="#27272a"
              interval={Math.floor(chartData.length / 12)}
            />
            <YAxis
              tick={{ fill: "#52525b", fontSize: 9, fontFamily: "ui-monospace" }}
              stroke="#27272a"
              tickFormatter={(v) => `${v.toFixed(0)}%`}
              label={{
                value: "Cumulative Return",
                fill: "#52525b", fontSize: 9, angle: -90,
                position: "insideLeft", offset: 0,
              }}
            />

            <Tooltip
              contentStyle={{
                background: "#0a0a0a",
                border: "1px solid #2a2a2a",
                borderRadius: 8,
                fontSize: 11,
                fontFamily: "ui-monospace",
                padding: "8px 12px",
              }}
              labelStyle={{ color: "#fafafa", fontWeight: 700, marginBottom: 4 }}
              formatter={(val: any, name: string) => {
                if (name === "ideal")   return [`${Number(val).toFixed(2)}%`, "Ideal"];
                if (name === "reality") return [`${Number(val).toFixed(2)}%`, "Reality"];
                if (name === "gap")     return [`${Number(val).toFixed(2)}%`, "Erosion Gap"];
                return [val, name];
              }}
              labelFormatter={(label, payload) => {
                const row = payload && payload[0]?.payload;
                const regimeInfo = row?.regime ? REGIME_LABEL[row.regime] : null;
                return `${row?.date}${regimeInfo ? ` · ${regimeInfo.label}` : ""}`;
              }}
              cursor={{ stroke: "#3f3f46", strokeWidth: 1, strokeDasharray: "3 3" }}
            />

            {/* Reality main area (mode=reality) or background (mode=ideal) */}
            <Area
              type="monotone"
              dataKey="reality"
              stroke="#DEFF9A"
              strokeWidth={mode === "reality" ? 2.5 : 1}
              fill="url(#realityFill)"
              fillOpacity={mode === "reality" ? 1 : 0.3}
              dot={false}
              isAnimationActive
              animationDuration={800}
            />

            {/* Ideal line — dashed when reality is active, solid when ideal active */}
            <Line
              type="monotone"
              dataKey="ideal"
              stroke="#DAFFDE"
              strokeWidth={mode === "ideal" ? 2.5 : 1.5}
              strokeDasharray={mode === "ideal" ? "0" : "5 4"}
              strokeOpacity={mode === "ideal" ? 1 : 0.5}
              dot={false}
              isAnimationActive
              animationDuration={800}
            />
          </ComposedChart>
        </ResponsiveContainer>

        {/* Regime band legend */}
        <div className="flex items-center justify-center gap-4 mt-3 text-[9px]">
          {Object.entries(REGIME_LABEL).map(([key, info]) => (
            <div key={key} className="flex items-center gap-1.5">
              <div
                className="w-2.5 h-2.5 rounded-sm"
                style={{ background: info.color, opacity: 0.6 }}
              />
              <span className="text-zinc-500 font-mono uppercase tracking-wider">
                {info.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        <StatBlock
          label="Ideal Total"
          value={`+${ideal.summary.total_return_pct.toFixed(2)}%`}
          color="#DAFFDE"
        />
        <StatBlock
          label="Reality Total"
          value={`+${reality.summary.total_return_pct.toFixed(2)}%`}
          color="#DEFF9A"
          highlight
        />
        <StatBlock
          label="Erosion"
          value={`${(reality.summary.total_return_pct - ideal.summary.total_return_pct).toFixed(2)}%`}
          color="#FF6B6B"
        />
      </div>
    </div>
  );
}

function StatBlock({ label, value, color, highlight }: {
  label: string; value: string; color: string; highlight?: boolean;
}) {
  return (
    <div
      className={`
        rounded-lg p-3 border
        ${highlight ? "bg-[#0f1209] border-[#DEFF9A]/20" : "bg-[#0d0d0d] border-zinc-800"}
      `}
    >
      <div className="text-[9px] uppercase tracking-wider text-zinc-500 font-bold mb-1">
        {label}
      </div>
      <div className="text-xl font-bold font-mono tabular-nums" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
