"use client";
// cockpitParts 의 차트(RegimeScatter, YieldCurveChart) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 본문은 cockpitParts.tsx 에 있던 그대로다. 소비자는 그 파일이 같은 이름으로 내보내는 것을 쓴다.
import { ResponsiveContainer, LineChart, Line, ScatterChart, Scatter, ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import type { YieldCurvePoint } from "@/entities/macro/api";
import { regimeName } from "@/entities/macro/regimeKo";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { signed } from "./macroKo";
import { TX_TIP_STYLE as TIP_STYLE } from "@/shared/ui/chartStyle";
import { AX, Q_FILL } from "./cockpitParts";

// ─────────────────────────────────────────────────────────────────────────────
// RegimeScatter — 성장(x) × 물가(y) 평면 + 네 국면 바탕(국면 색) + 지금 위치
// ─────────────────────────────────────────────────────────────────────────────
export function RegimeScatter({ g, i }: { g: number; i: number }) {
  const anim = useChartAnimation();
  // 동적 스케일: 축 한계를 데이터에 맞춰 넓힌다(점수가 ±1 을 넘으면 점이 잘리던 버그 수정 — 그대로).
  const lim = Math.max(1, Math.ceil(Math.max(Math.abs(g), Math.abs(i))));
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim];
  const pt = [{ x: g, y: i }];
  return (
    <div className="mc-scatter" role="img" aria-label={`성장 ${signed(g)}, 물가 ${signed(i)}`}>
      <span className="mc-quad tr" data-regime="Reflation">{regimeName("Reflation")}<em>성장↑ 물가↑</em></span>
      <span className="mc-quad tl" data-regime="Stagflation">{regimeName("Stagflation")}<em>성장↓ 물가↑</em></span>
      <span className="mc-quad br" data-regime="Goldilocks">{regimeName("Goldilocks")}<em>성장↑ 물가↓</em></span>
      <span className="mc-quad bl" data-regime="Disinflation">{regimeName("Disinflation")}<em>성장↓ 물가↓</em></span>
      <ResponsiveContainer width="100%" height={340}>
        <ScatterChart margin={{ top: 14, right: 18, bottom: 22, left: 6 }}>
          <ReferenceArea x1={0} x2={lim} y1={-lim} y2={0} fill={Q_FILL.Goldilocks} fillOpacity={0.1} stroke="none" />
          <ReferenceArea x1={0} x2={lim} y1={0} y2={lim} fill={Q_FILL.Reflation} fillOpacity={0.1} stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={0} y2={lim} fill={Q_FILL.Stagflation} fillOpacity={0.1} stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={-lim} y2={0} fill={Q_FILL.Disinflation} fillOpacity={0.1} stroke="none" />
          <XAxis type="number" dataKey="x" domain={[-lim, lim]} ticks={ticks} tick={AX} stroke="var(--tx-line)" label={{ value: "성장 →", position: "insideBottom", offset: -10, ...AX }} />
          <YAxis type="number" dataKey="y" domain={[-lim, lim]} ticks={ticks} tick={AX} stroke="var(--tx-line)" label={{ value: "물가 →", angle: -90, position: "insideLeft", ...AX }} />
          <ReferenceLine x={0} stroke="var(--tx-mute)" strokeWidth={1} />
          <ReferenceLine y={0} stroke="var(--tx-mute)" strokeWidth={1} />
          <ReferenceDot x={g} y={i} r={14} fill="var(--tx-ink)" fillOpacity={0.1} stroke="none" />
          <ReferenceDot x={g} y={i} r={5} fill="var(--tx-ink)" stroke="var(--tx-surface)" strokeWidth={2} />
          <Scatter data={pt} fill="var(--tx-ink)" fillOpacity={0} isAnimationActive={anim} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── YieldCurveChart — 미국 국채 수익률 곡선(3개월~30년). 선은 한 계열 강조색 — 역전 여부는 제목 옆 글자가 말한다. ──
export function YieldCurveChart({ points }: { points: YieldCurvePoint[]; inversion?: boolean }) {
  const anim = useChartAnimation();
  const data = points.map((p) => ({ label: p.label, y: p.yield_pct }));
  return (
    <ResponsiveContainer width="100%" height={210}>
      <LineChart data={data} margin={{ top: 12, right: 18, bottom: 4, left: -8 }}>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--tx-line)" vertical={false} />
        <XAxis dataKey="label" tick={AX} stroke="var(--tx-line)" />
        <YAxis tick={AX} stroke="var(--tx-line)" domain={["auto", "auto"]} unit="%" width={48} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string) => [`${val}%`, "수익률"]} />
        <Line type="monotone" dataKey="y" stroke="var(--tx-blue)" strokeWidth={2} dot={{ r: 3, fill: "var(--tx-blue)" }} activeDot={{ r: 4 }} isAnimationActive={anim} />
      </LineChart>
    </ResponsiveContainer>
  );
}
