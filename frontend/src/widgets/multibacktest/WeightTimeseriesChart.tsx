"use client";

import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { useChartAnimation } from "@/shared/ui/chartStyle";

interface DailyRecord {
  date: string;
  weights: Record<string, number>;
  rebalanced?: boolean;
  regime?: string;
}

interface Props {
  daily: DailyRecord[];
  strategyNames: Record<number, string>;
  maxPoints?: number;
}

const COLORS = [
  "#1200ff", "#00e5ff", "#69f0ae", "#ffeb3b",
  "#ff9800", "#e040fb", "#ff5252", "#42a5f5",
];

export default function WeightTimeseriesChart({
  daily, strategyNames, maxPoints = 250,
}: Props) {
  const anim = useChartAnimation();
  if (!daily || daily.length === 0) {
    return (
      <div style={{
        padding: 40, textAlign: "center", color: "#6b7fa3",
        fontSize: 12, fontStyle: "italic",
      }}>
        가중치 시계열 데이터 없음
      </div>
    );
  }

  // 압축 (대용량 시계열)
  const step = Math.max(1, Math.floor(daily.length / maxPoints));
  const compressed = daily.filter((_, i) => i % step === 0 || i === daily.length - 1);

  // strategy IDs (첫 row의 weights 키)
  const strategyIds = Object.keys(daily[0].weights || {}).map(Number).sort((a, b) => a - b);

  // 차트용 데이터 변환 (퍼센트 단위)
  const chartData = compressed.map((r) => {
    const row: any = {
      date: r.date,
      shortDate: r.date.slice(5),  // MM-DD
      rebalanced: r.rebalanced,
      regime: r.regime,
    };
    for (const sid of strategyIds) {
      const w = (r.weights[String(sid)] || 0) * 100;
      row[`s_${sid}`] = w;
    }
    return row;
  });

  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: 10, color: "#6b7fa3",
                      display: "flex", justifyContent: "space-between" }}>
        <span>일별 가중치 시계열 — {strategyIds.length}개 전략 (압축: {daily.length} → {compressed.length} points)</span>
        <span style={{ color: "#a7c8ff" }}>
          {compressed.filter((r) => r.rebalanced).length}회 리밸런싱
        </span>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={chartData}
                    margin={{ top: 5, right: 16, bottom: 5, left: 30 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1e2d4a" />
          <XAxis dataKey="shortDate"
                  tick={{ fill: "#6b7fa3", fontSize: 9 }}
                  stroke="#1e2d4a"
                  interval={Math.floor(chartData.length / 15)} />
          <YAxis tick={{ fill: "#6b7fa3", fontSize: 9 }}
                  stroke="#1e2d4a"
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`} />
          <Tooltip
            contentStyle={{
              background: "#060a1a", border: "1px solid #1e2d4a",
              borderRadius: 4, fontSize: 11,
            }}
            labelStyle={{ color: "#e0e8f5", fontWeight: 600 }}
            formatter={(v: any, name: string) => {
              const sid = Number(name.replace("s_", ""));
              return [
                `${Number(v).toFixed(1)}%`,
                strategyNames[sid] || `#${sid}`,
              ];
            }}
            labelFormatter={(label, payload) => {
              const row = payload && payload[0]?.payload;
              return `${row?.date} ${row?.regime ? `(${row.regime})` : ""}`;
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "#6b7fa3" }}
            iconSize={8}
            formatter={(value: string) => {
              const sid = Number(value.replace("s_", ""));
              return strategyNames[sid] || `#${sid}`;
            }}
          />

          {strategyIds.map((sid, i) => (
            <Area isAnimationActive={anim} key={sid}
                  type="monotone"
                  dataKey={`s_${sid}`}
                  stackId="1"
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.85}
                  strokeWidth={1} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
