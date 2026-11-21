"use client";
// StudioPanel 의 선 그림 셋(요인이 지나온 길 · 곡선의 세 요인 · 기간프리미엄 대용) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다
// (ADR 004 · 2026-11-10 — recharts 는 차트 파일에서만 import 한다 · `e2e/charts-lazy.spec.ts`). 행 만들기는 StudioPanel 에 남는다.
// ★값은 호버 툴팁이 아니라 읽는 줄·표 쌍둥이에 있다★(ADR 004 §2.4 · §6) — 처음 자리 = 마지막 관측 · ←→ Home End · 마우스를 올려도 옮겨진다.
//   글자는 예전 툴팁과 같은 서식이다. 계열이 여럿이면 읽는 줄의 선 표식이 범례 구실도 한다.
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, ReferenceLine } from "recharts";
import { ReadoutFrame, followChart, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { AXIS_TICK, CROSSHAIR, MARK, minus } from "@/shared/ui/chart/chartSpec";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { catColor, signed } from "./macroKo";

const AXIS = { tick: AXIS_TICK, stroke: "var(--tx-line)" } as const;
const sixth = (n: number) => Math.max(0, Math.floor(n / 6));
const head = (i: number) => `관측 ${i}번째`;
/** 그 관측에 값이 없으면 "없어요" — 0 으로 적지 않는다. */
const cell = (v: number | undefined, fmt: (x: number) => string) => (typeof v === "number" && Number.isFinite(v) ? fmt(v) : "없습니다");

/** 요인이 지나온 길 — 행 = { i, f1, f2, … } · 요인 k 개(하나면 강조색, 여럿이면 범주색). */
export function FactorLines({ rows, k }: { rows: Record<string, number>[]; k: number }) {
  const anim = useChartAnimation();
  const color = (j: number) => (k === 1 ? "var(--tx-blue)" : catColor(j));
  const read: ReadRow[] = rows.map((r) => ({ head: head(r.i), cells: Array.from({ length: k }, (_, j) => ({
    key: `f${j + 1}`, label: `요인 ${j + 1}`, text: cell(r[`f${j + 1}`], (x) => signed(x, 3)), ...(k > 1 ? { color: color(j) } : {}) })) }));
  const { idx, setIdx, onKeyDown } = useReadout(read.length);
  return (
    <ReadoutFrame id="studio-factor" label="요인이 지나온 길" headLabel="관측" rows={read} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }} onMouseMove={followChart(setIdx)}>
          <XAxis dataKey="i" {...AXIS} interval={sixth(rows.length)} />
          <YAxis width={36} {...AXIS} />
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          {Array.from({ length: k }, (_, j) => (
            <Line key={j} dataKey={`f${j + 1}`} stroke={color(j)} strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />
          ))}
          {idx >= 0 && <ReferenceLine x={rows[idx].i} {...CROSSHAIR} />}
        </LineChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

/** 곡선의 세 요인이 지나온 길 — `cols` = [키, 한국어 이름][] (서버가 준 것만). */
export function CurveLines({ rows, cols }: { rows: Record<string, number>[]; cols: [string, string][] }) {
  const anim = useChartAnimation();
  const read: ReadRow[] = rows.map((r) => ({ head: head(r.i), cells: cols.map(([key, ko], j) => ({
    key, label: ko, text: cell(r[key], (x) => minus(x.toFixed(2))), color: catColor(j) })) }));
  const { idx, setIdx, onKeyDown } = useReadout(read.length);
  return (
    <ReadoutFrame id="studio-curve" label="곡선의 세 요인이 지나온 길" headLabel="관측" rows={read} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={210}>
        <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }} onMouseMove={followChart(setIdx)}>
          <XAxis dataKey="i" {...AXIS} interval={sixth(rows.length)} />
          <YAxis width={36} {...AXIS} />
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          {cols.map(([key], j) => <Line key={key} dataKey={key} stroke={catColor(j)} strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />)}
          {idx >= 0 && <ReferenceLine x={rows[idx].i} {...CROSSHAIR} />}
        </LineChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

/** 기간프리미엄 대용(bp) — 행 = { i, tp }. */
export function TpLine({ rows }: { rows: { i: number; tp: number }[] }) {
  const anim = useChartAnimation();
  const read: ReadRow[] = rows.map((r) => ({ head: head(r.i), cells: [{ key: "tp", label: "기간프리미엄 대용", text: cell(r.tp, (x) => minus(x.toFixed(1))) }] }));
  const { idx, setIdx, onKeyDown } = useReadout(read.length);
  return (
    <ReadoutFrame id="studio-tp" label="기간프리미엄 대용" headLabel="관측" rows={read} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }} onMouseMove={followChart(setIdx)}>
          <XAxis dataKey="i" {...AXIS} interval={sixth(rows.length)} />
          <YAxis width={40} {...AXIS} />
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          <Line dataKey="tp" stroke="var(--tx-blue)" strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />
          {idx >= 0 && <ReferenceLine x={rows[idx].i} {...CROSSHAIR} />}
        </LineChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}
