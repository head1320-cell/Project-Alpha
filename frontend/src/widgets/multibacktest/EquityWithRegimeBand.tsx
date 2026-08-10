"use client";

import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceArea,
} from "recharts";
import { useMemo } from "react";
import { useChartAnimation } from "@/shared/ui/chartStyle";

interface DailyRecord {
  date: string;
  portfolio_equity: number;
  cumulative_return: number;
  drawdown_pct: number;
  regime?: string;
}

interface Props {
  daily: DailyRecord[];
  initialCapital: number;
  maxPoints?: number;
}

const REGIME_COLORS: Record<string, string> = {
  GOLDILOCKS:  "rgba(105,240,174,0.10)",
  REFLATION:   "rgba(255,235,59,0.10)",
  STAGFLATION: "rgba(255,82,82,0.10)",
  DEFLATION:   "rgba(66,165,245,0.10)",
};

export default function EquityWithRegimeBand({
  daily, initialCapital, maxPoints = 300,
}: Props) {
  const anim = useChartAnimation();
  // 압축 + chartData
  const { chartData, regimeBands } = useMemo(() => {
    if (!daily || daily.length === 0) {
      return { chartData: [], regimeBands: [] };
    }

    const step = Math.max(1, Math.floor(daily.length / maxPoints));
    const compressed = daily.filter((_, i) => i % step === 0 || i === daily.length - 1);

    // 차트 데이터
    const chartData = compressed.map((r) => ({
      date:               r.date,
      shortDate:          r.date.slice(5),
      equity:             r.portfolio_equity,
      cumulative_return:  r.cumulative_return,
      drawdown:           r.drawdown_pct,
      regime:             r.regime,
    }));

    // Regime bands (연속된 동일 regime 묶기)
    const bands: { start: string; end: string; regime: string }[] = [];
    let currentRegime = compressed[0]?.regime;
    let currentStart = compressed[0]?.date;

    for (let i = 1; i < compressed.length; i++) {
      const r = compressed[i].regime;
      if (r !== currentRegime) {
        if (currentRegime && currentStart) {
          bands.push({
            start: currentStart,
            end: compressed[i - 1].date,
            regime: currentRegime,
          });
        }
        currentRegime = r;
        currentStart = compressed[i].date;
      }
    }
    if (currentRegime && currentStart) {
      bands.push({
        start: currentStart,
        end: compressed[compressed.length - 1].date,
        regime: currentRegime,
      });
    }

    return { chartData, regimeBands: bands };
  }, [daily, maxPoints]);

  if (chartData.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#6b7fa3", fontSize: 12 }}>
        자산 곡선 데이터 없음
      </div>
    );
  }

  // ChartData 인덱스로 변환
  const dateToIdx: Record<string, number> = {};
  chartData.forEach((d, i) => { dateToIdx[d.date] = i; });

  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: 10, color: "#6b7fa3",
                      display: "flex", justifyContent: "space-between" }}>
        <span>자산 곡선 (배경: 매크로 국면)</span>
        <span style={{ display: "flex", gap: 12 }}>
          {Object.entries(REGIME_COLORS).map(([regime, color]) => (
            <span key={regime} style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <span style={{
                width: 10, height: 10, borderRadius: 2,
                background: color.replace("0.10", "0.6"),
                display: "inline-block",
              }} />
              <span style={{ fontSize: 9, color: "#6b7fa3" }}>{regime}</span>
            </span>
          ))}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 16, bottom: 5, left: 50 }}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00e5ff" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#00e5ff" stopOpacity={0.05} />
            </linearGradient>
          </defs>

          {/* Regime bands as background */}
          {regimeBands.map((band, i) => (
            <ReferenceArea
              key={i}
              x1={chartData[dateToIdx[band.start]]?.shortDate}
              x2={chartData[dateToIdx[band.end]]?.shortDate}
              fill={REGIME_COLORS[band.regime] || "transparent"}
              fillOpacity={1}
            />
          ))}

          <CartesianGrid strokeDasharray="2 4" stroke="#1e2d4a" />
          <XAxis dataKey="shortDate"
                  tick={{ fill: "#6b7fa3", fontSize: 9 }}
                  stroke="#1e2d4a"
                  interval={Math.floor(chartData.length / 15)} />
          <YAxis yAxisId="left"
                  tick={{ fill: "#6b7fa3", fontSize: 9 }}
                  stroke="#1e2d4a"
                  tickFormatter={(v) => `${(v / 10000).toFixed(0)}만`}
                  label={{ value: "Equity (원)", fill: "#6b7fa3", fontSize: 9,
                            angle: -90, position: "insideLeft" }} />
          <YAxis yAxisId="right" orientation="right"
                  tick={{ fill: "#ff5252", fontSize: 9 }}
                  stroke="#1e2d4a"
                  tickFormatter={(v) => `${v.toFixed(0)}%`}
                  domain={[(dataMin: number) => Math.floor(dataMin * 1.2), 0]} />

          <Tooltip
            contentStyle={{ background: "#060a1a", border: "1px solid #1e2d4a",
                              borderRadius: 4, fontSize: 11 }}
            labelStyle={{ color: "#e0e8f5", fontWeight: 600 }}
            formatter={(v: any, name: string) => {
              if (name === "equity") return [`${Number(v).toLocaleString()}원`, "Equity"];
              if (name === "drawdown") return [`${Number(v).toFixed(2)}%`, "Drawdown"];
              return [v, name];
            }}
            labelFormatter={(label, payload) => {
              const row = payload && payload[0]?.payload;
              return `${row?.date} ${row?.regime ? `(${row.regime})` : ""}`;
            }}
          />

          <Area isAnimationActive={anim} yAxisId="left" type="monotone" dataKey="equity"
                 stroke="#00e5ff" strokeWidth={2}
                 fill="url(#equityGrad)" />
          <Line isAnimationActive={anim} yAxisId="right" type="monotone" dataKey="drawdown"
                 stroke="#ff5252" strokeWidth={1} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
