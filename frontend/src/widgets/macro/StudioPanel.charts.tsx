"use client";
// StudioPanel 의 선 그림 셋(요인이 지나온 길 · 곡선의 세 요인 · 기간프리미엄 대용) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다
// (ADR 004 · 2026-11-10 — recharts 는 차트 파일에서만 import 한다 · `e2e/charts-lazy.spec.ts`). 예전에는 StudioPanel.tsx 가 recharts 를
// 직접 import 해 스튜디오 네 페이지의 초기 script 에 실려 있었다. 본문은 그 파일에 있던 그대로다(행 만들기는 StudioPanel 에 남는다).
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine } from "recharts";
import { TX_TIP_STYLE as TIP_STYLE, useChartAnimation } from "@/shared/ui/chartStyle";
import { AXIS_TICK, MARK } from "@/shared/ui/chart/chartSpec";
import { catColor, signed } from "./macroKo";

const AXIS = { tick: AXIS_TICK, stroke: "var(--tx-line)" } as const;
const sixth = (n: number) => Math.max(0, Math.floor(n / 6));

/** 요인이 지나온 길 — 행 = { i, f1, f2, … } · 요인 k 개(하나면 강조색, 여럿이면 범주색). */
export function FactorLines({ rows, k }: { rows: Record<string, number>[]; k: number }) {
  const anim = useChartAnimation();
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }}>
        <XAxis dataKey="i" {...AXIS} interval={sixth(rows.length)} />
        <YAxis width={36} {...AXIS} />
        <ReferenceLine y={0} stroke="var(--tx-mute)" />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number, n: string) => [signed(Number(v), 3), `요인 ${n.slice(1)}`]} labelFormatter={(l) => `관측 ${l}번째`} />
        {Array.from({ length: k }, (_, j) => (
          <Line key={j} dataKey={`f${j + 1}`} stroke={k === 1 ? "var(--tx-blue)" : catColor(j)} strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** 곡선의 세 요인이 지나온 길 — `cols` = [키, 한국어 이름][] (서버가 준 것만). */
export function CurveLines({ rows, cols }: { rows: Record<string, number>[]; cols: [string, string][] }) {
  const anim = useChartAnimation();
  return (
    <ResponsiveContainer width="100%" height={210}>
      <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }}>
        <XAxis dataKey="i" {...AXIS} interval={sixth(rows.length)} />
        <YAxis width={36} {...AXIS} />
        <ReferenceLine y={0} stroke="var(--tx-mute)" />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number, k: string) => [Number(v).toFixed(2), cols.find(([x]) => x === k)?.[1] ?? k]} labelFormatter={(l) => `관측 ${l}번째`} />
        {cols.map(([k], j) => <Line key={k} dataKey={k} stroke={catColor(j)} strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />)}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** 기간프리미엄 대용(bp) — 행 = { i, tp }. */
export function TpLine({ rows }: { rows: { i: number; tp: number }[] }) {
  const anim = useChartAnimation();
  return (
    <ResponsiveContainer width="100%" height={170}>
      <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }}>
        <XAxis dataKey="i" {...AXIS} interval={sixth(rows.length)} />
        <YAxis width={40} {...AXIS} />
        <ReferenceLine y={0} stroke="var(--tx-mute)" />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number) => [Number(v).toFixed(1), "기간프리미엄 대용"]} labelFormatter={(l) => `관측 ${l}번째`} />
        <Line dataKey="tp" stroke="var(--tx-blue)" strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />
      </LineChart>
    </ResponsiveContainer>
  );
}
