"use client";
// visualParts 의 차트(AxisStackChart) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 본문은 visualParts.tsx 에 있던 그대로다. 소비자는 그 파일이 같은 이름으로 내보내는 것을 쓴다.
import { ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ReferenceLine } from "recharts";
import type { AxisHistory } from "@/entities/macro/analysisModel";
import { AXIS_TICK, MARK } from "@/shared/ui/chart/chartSpec";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { IND_KR, catColor, signed, ym } from "./macroKo";
import { TIP_STYLE } from "./cockpitParts";

// ── 축 하위요인: 축 점수 = 지표 기여 쌓기(막대) + 축 점수(선) ──
export function AxisStackChart({ hist, axis }: { hist: AxisHistory; axis: "growth" | "inflation" }) {
  const anim = useChartAnimation();
  const partsKey = axis === "growth" ? "growth_parts" : "inflation_parts";
  const keys = Array.from(new Set(hist.points.flatMap((p) => Object.keys(p[partsKey] ?? {}))));
  const data = hist.points.map((p) => ({
    t: ym(p.t), score: p[axis],
    ...Object.fromEntries(keys.map((k) => [k, p[partsKey]?.[k] ?? 0])),
  }));
  const axisName = axis === "growth" ? "성장 축" : "물가 축";
  return (
    <div className="mc-axstack">
      <ResponsiveContainer width="100%" height={210}>
        <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -14 }} stackOffset="sign">
          <XAxis dataKey="t" tick={AXIS_TICK} stroke="var(--tx-line)" interval={Math.max(0, Math.floor(data.length / 5))} />
          <YAxis tick={AXIS_TICK} stroke="var(--tx-line)" />
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          <Tooltip contentStyle={TIP_STYLE} formatter={(v: number | string, name: string) => [signed(Number(v), 3), IND_KR[name] ?? (name === "score" ? axisName : name)]} />
          {keys.map((k, i) => (
            <Bar key={k} dataKey={k} stackId="s" fill={catColor(i)} isAnimationActive={anim} />
          ))}
          <Line dataKey="score" stroke="var(--tx-ink)" strokeWidth={MARK.line} dot={false} isAnimationActive={anim} name="score" />
        </ComposedChart>
      </ResponsiveContainer>
      <ul className="mc-legend">
        {keys.map((k, i) => <li key={k}><i style={{ background: catColor(i) }} aria-hidden />{IND_KR[k] ?? k}</li>)}
        <li><i className="mc-legend-line" aria-hidden />{axisName} 점수</li>
      </ul>
    </div>
  );
}
