"use client";
// visualParts 의 차트(AxisStackChart) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 소비자는 visualParts.tsx 가 같은 이름으로 내보내는 것을 쓴다.
// ★값은 호버 툴팁이 아니라 읽는 줄·표 쌍둥이에 있다★(ADR 004 §2.4 · §6 · 2026-11-10) — 읽는 줄의 선 표식이 범례 구실도 한다(따로 범례를 두지 않는다).
import { useMemo } from "react";
import { ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, ReferenceLine } from "recharts";
import type { AxisHistory } from "@/entities/macro/analysisModel";
import { ReadoutFrame, followChart, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { AXIS_TICK, CROSSHAIR, MARK } from "@/shared/ui/chart/chartSpec";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { IND_KR, catColor, signed, ym } from "./macroKo";

// ── 축 하위요인: 축 점수 = 지표 기여 쌓기(막대) + 축 점수(선) ──
export function AxisStackChart({ hist, axis }: { hist: AxisHistory; axis: "growth" | "inflation" }) {
  const anim = useChartAnimation();
  const partsKey = axis === "growth" ? "growth_parts" : "inflation_parts";
  const keys = useMemo(() => Array.from(new Set(hist.points.flatMap((p) => Object.keys(p[partsKey] ?? {})))), [hist, partsKey]);
  // 자료 배열은 고정한다 — 읽는 줄 자리가 바뀔 때마다 새 배열을 넘기면 recharts 가 자료가 바뀐 것으로 본다.
  const data = useMemo(() => hist.points.map((p) => ({
    t: ym(p.t), score: p[axis],
    ...Object.fromEntries(keys.map((k) => [k, p[partsKey]?.[k] ?? 0])),
  })), [hist, axis, partsKey, keys]);
  const axisName = axis === "growth" ? "성장 축" : "물가 축";
  // 읽는 줄 — 달마다 축 점수와 지표 기여(예전 툴팁과 같은 서식). 그 달에 없는 지표는 "없어요" — 막대는 높이가 없을 뿐이고 0 이라고 적지 않는다.
  const rows: ReadRow[] = hist.points.map((p) => ({ head: ym(p.t), cells: [
    { key: "score", label: `${axisName} 점수`, text: signed(p[axis], 3), color: "var(--tx-ink)" },
    ...keys.map((k, i) => {
      const v = p[partsKey]?.[k];
      return { key: k, label: IND_KR[k] ?? k, text: typeof v === "number" ? signed(v, 3) : "없습니다", color: catColor(i) };
    }),
  ] }));
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  const cur = idx >= 0 ? data[idx] : null;
  return (
    <div className="mc-axstack">
      <ReadoutFrame id={`axis-stack-${axis}`} label={`${axisName} 점수와 지표 기여`} headLabel="달" rows={rows} idx={idx} onKeyDown={onKeyDown}>
        <ResponsiveContainer width="100%" height={210}>
          <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -14 }} stackOffset="sign" onMouseMove={followChart(setIdx)}>
            <XAxis dataKey="t" tick={AXIS_TICK} stroke="var(--tx-line)" interval={Math.max(0, Math.floor(data.length / 5))} />
            <YAxis tick={AXIS_TICK} stroke="var(--tx-line)" />
            <ReferenceLine y={0} stroke="var(--tx-mute)" />
            {keys.map((k, i) => (
              <Bar key={k} dataKey={k} stackId="s" fill={catColor(i)} isAnimationActive={anim} />
            ))}
            <Line dataKey="score" stroke="var(--tx-ink)" strokeWidth={MARK.line} dot={false} isAnimationActive={anim} name="score" />
            {cur && <ReferenceLine x={cur.t} {...CROSSHAIR} />}
          </ComposedChart>
        </ResponsiveContainer>
      </ReadoutFrame>
    </div>
  );
}
