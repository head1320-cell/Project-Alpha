"use client";
// analyticsParts 의 차트(RollingCorrChart, AvgCorrChart, TimingHistory, RegimeTrajectory) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 본문은 analyticsParts.tsx 에 있던 그대로다. 소비자는 그 파일이 같은 이름으로 내보내는 것을 쓴다.
import { ResponsiveContainer, LineChart, Line, AreaChart, Area, ScatterChart, Scatter, ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import type { MacroCorrelations, MacroTiming, TrajectoryPoint } from "@/entities/macro/analysisModel";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { regimeName } from "@/entities/macro/regimeKo";
import { TIP_STYLE } from "./cockpitParts";
import { catColor, signed } from "./macroKo";
import { AX, inkLegend } from "./analyticsParts";

// ── RollingCorrChart — 60일 롤링 상관 추이 (주식·장기채를 굵게) ──
export function RollingCorrChart({ pairs }: { pairs: MacroCorrelations["pairs"] }) {
  const anim = useChartAnimation();
  if (!pairs.length) return <div className="mc-empty-sm">롤링 상관을 그릴 자료가 없어요</div>;
  const len = Math.max(...pairs.map((p) => p.series.length));
  const data = Array.from({ length: len }, (_, i) => {
    const row: Record<string, string | number> = { t: pairs[0].series[i]?.t ?? "" };
    for (const p of pairs) { const v = p.series[i]?.corr; if (v != null) row[p.key] = v; }
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--tx-line)" vertical={false} />
        <XAxis dataKey="t" tick={AX} stroke="var(--tx-line)" minTickGap={32} />
        <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]} tick={AX} stroke="var(--tx-line)" width={36} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number | string, n: string) => [signed(Number(v)), n]} />
        <Legend wrapperStyle={{ fontSize: 13 }} formatter={inkLegend} />
        <ReferenceLine y={0} stroke="var(--tx-mute)" strokeWidth={1} />
        {pairs.map((p, i) => (
          <Line key={p.key} type="monotone" dataKey={p.key} name={p.label}
            stroke={catColor(i)} strokeWidth={p.key === "SPY-TLT" ? 2.6 : 1.4}
            dot={false} isAnimationActive={anim} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── AvgCorrChart — 모든 자산 쌍의 평균 상관(분산이 잘 되는지). 0.6 선은 화면이 그은 참고선(서버 판정 아님). ──
export function AvgCorrChart({ avg }: { avg: MacroCorrelations["avg_corr"] }) {
  const anim = useChartAnimation();
  if (!avg.length) return <div className="mc-empty-sm">평균 상관을 그릴 자료가 없어요</div>;
  const data = avg.map((p) => ({ t: p.t, corr: p.corr }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
        <defs><linearGradient id="mcaAvg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--tx-blue)" stopOpacity={0.22} /><stop offset="100%" stopColor="var(--tx-blue)" stopOpacity={0.02} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--tx-line)" vertical={false} />
        <XAxis dataKey="t" tick={AX} stroke="var(--tx-line)" minTickGap={32} />
        <YAxis domain={[0, 1]} tick={AX} stroke="var(--tx-line)" width={36} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number | string) => [Number(v).toFixed(2), "평균 상관"]} />
        <ReferenceLine y={0.6} stroke="var(--tx-mute)" strokeDasharray="3 3" label={{ value: "참고선 0.6", position: "insideTopRight", fontSize: 12, fill: "var(--tx-sub)" }} />
        <Area type="monotone" dataKey="corr" stroke="var(--tx-blue)" strokeWidth={1.8} fill="url(#mcaAvg)" isAnimationActive={anim} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── TimingHistory — 위험 선호도 추이. 60·40 선은 서버 라벨 규칙(위험 선호 ≥60 · 위험 회피 ≤40)과 같은 값 — 색 없이 글자로. ──
export function TimingHistory({ history }: { history: MacroTiming["history"] }) {
  const anim = useChartAnimation();
  if (!history.length) return <div className="mc-empty-sm">위험 선호도 추이를 그릴 자료가 없어요</div>;
  return (
    <ResponsiveContainer width="100%" height={210}>
      <AreaChart data={history} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        <defs><linearGradient id="mcaTim" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--tx-blue)" stopOpacity={0.22} /><stop offset="100%" stopColor="var(--tx-blue)" stopOpacity={0.02} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--tx-line)" vertical={false} />
        <XAxis dataKey="t" tick={AX} stroke="var(--tx-line)" minTickGap={28} />
        <YAxis domain={[0, 100]} ticks={[0, 40, 60, 100]} tick={AX} stroke="var(--tx-line)" width={36} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number | string) => [Number(v).toFixed(0), "위험 선호도"]} />
        <ReferenceLine y={60} stroke="var(--tx-mute)" strokeDasharray="3 3" label={{ value: "위험 선호(60 이상)", position: "insideBottomLeft", fontSize: 12, fill: "var(--tx-sub)" }} />
        <ReferenceLine y={40} stroke="var(--tx-mute)" strokeDasharray="3 3" label={{ value: "위험 회피(40 이하)", position: "insideTopLeft", fontSize: 12, fill: "var(--tx-sub)" }} />
        <Area type="monotone" dataKey="score" stroke="var(--tx-blue)" strokeWidth={1.8} fill="url(#mcaTim)" isAnimationActive={anim} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── RegimeTrajectory — 국면 궤적(경로) 산점도 ──
export function RegimeTrajectory({ path }: { path: TrajectoryPoint[] }) {
  // BU5b-1: 국면 바탕 = 국면 색(`--mc-q-*`, 도넛과 같은 네 색) · 사분면 이름 한국어 · 길은 한 계열 강조색 · 지금 점은 잉크.
  const anim = useChartAnimation();
  if (!path.length) return <div className="mc-empty-sm">궤적을 그릴 관측이 없어요</div>;
  const data = path.map((p) => ({ x: p.growth, y: p.inflation, t: p.t }));
  const last = data[data.length - 1];
  // 동적 스케일 — 궤적 전체가 축 안에 들어오도록.
  const lim = Math.max(1, Math.ceil(Math.max(...data.map((d) => Math.max(Math.abs(d.x), Math.abs(d.y))))));
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim];
  const AX = { fontSize: 12, fill: "var(--tx-sub)" } as const;
  return (
    <div className="mc-scatter" role="img" aria-label={`국면 궤적 ${data.length}개월 · 지금 성장 ${last.x.toFixed(2)}, 물가 ${last.y.toFixed(2)}`}>
      <span className="mc-quad tr" data-regime="Reflation">{regimeName("Reflation")}<em>성장↑ 물가↑</em></span>
      <span className="mc-quad tl" data-regime="Stagflation">{regimeName("Stagflation")}<em>성장↓ 물가↑</em></span>
      <span className="mc-quad br" data-regime="Goldilocks">{regimeName("Goldilocks")}<em>성장↑ 물가↓</em></span>
      <span className="mc-quad bl" data-regime="Disinflation">{regimeName("Disinflation")}<em>성장↓ 물가↓</em></span>
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 14, right: 18, bottom: 22, left: 6 }}>
          <ReferenceArea x1={0} x2={lim} y1={-lim} y2={0} fill="var(--mc-q-goldilocks)" fillOpacity={0.1} stroke="none" />
          <ReferenceArea x1={0} x2={lim} y1={0} y2={lim} fill="var(--mc-q-reflation)" fillOpacity={0.1} stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={0} y2={lim} fill="var(--mc-q-stagflation)" fillOpacity={0.1} stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={-lim} y2={0} fill="var(--mc-q-disinflation)" fillOpacity={0.1} stroke="none" />
          <XAxis type="number" dataKey="x" domain={[-lim, lim]} ticks={ticks} tick={AX} stroke="var(--tx-line)" label={{ value: "성장 →", position: "insideBottom", offset: -10, ...AX }} />
          <YAxis type="number" dataKey="y" domain={[-lim, lim]} ticks={ticks} tick={AX} stroke="var(--tx-line)" label={{ value: "물가 →", angle: -90, position: "insideLeft", ...AX }} />
          <ReferenceLine x={0} stroke="var(--tx-mute)" />
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          <Tooltip contentStyle={{ background: "var(--tx-surface)", border: "1px solid var(--tx-line)", borderRadius: 12, fontSize: 13, color: "var(--tx-ink)" }}
            cursor={{ strokeDasharray: "3 3" }} formatter={(v: number | string, n: string) => [Number(v).toFixed(2), n === "x" ? "성장" : n === "y" ? "물가" : n]} />
          <Scatter data={data} line={{ stroke: "var(--tx-blue)", strokeWidth: 1.5 }} lineType="joint"
            fill="var(--tx-blue)" fillOpacity={0.5} isAnimationActive={anim} />
          <ReferenceDot x={last.x} y={last.y} r={14} fill="var(--tx-ink)" fillOpacity={0.1} stroke="none" />
          <ReferenceDot x={last.x} y={last.y} r={5} fill="var(--tx-ink)" stroke="var(--tx-surface)" strokeWidth={2} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
