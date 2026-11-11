"use client";
// analyticsParts 의 차트(RollingCorrChart, AvgCorrChart, TimingHistory, RegimeTrajectory) — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 소비자는 analyticsParts.tsx 가 같은 이름으로 내보내는 것을 쓴다.
// ★값은 호버 툴팁이 아니라 읽는 줄·표 쌍둥이에 있다★(ADR 004 §2.4 · 2026-11-10) — `<Tooltip>` 없음 · 처음 자리 = 마지막 점 ·
//   ←→ Home End · 마우스를 올려도 옮겨진다(`idxFromChartEvent`) · 고른 자리는 세로선(산점도는 고리)으로 보인다. 글자는 예전 툴팁과 같은 서식.
import { useMemo } from "react";
import { ResponsiveContainer, LineChart, Line, AreaChart, Area, ScatterChart, Scatter, ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Legend } from "recharts";
import type { MacroCorrelations, MacroTiming, TrajectoryPoint } from "@/entities/macro/analysisModel";
import { ReadoutFrame, followChart, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { CROSSHAIR, GRID, MARK, pickDot } from "@/shared/ui/chart/chartSpec";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { regimeName } from "@/entities/macro/regimeKo";
import { catColor, signed } from "./macroKo";
import { AX, inkLegend } from "./analyticsParts";

// 자료 배열은 useMemo 로 고정한다 — 읽는 줄 자리가 바뀔 때마다 이 부품이 다시 그려지는데, 그때 새 배열을 넘기면 recharts 가
// "자료가 바뀌었다"로 보고 애니메이션 주기를 다시 돈다. 재 보니 같은 자리로 보간이라 선이 다시 그려져 보이지는 않았다(프레임 지문 1) —
// 그래도 호버마다 할 일이 아니다(예전엔 호버 상태가 recharts 안에 있어 이 부품이 다시 그려지지 않았다).
const DOT = pickDot("var(--tx-blue)");

// ── RollingCorrChart — 60일 롤링 상관 추이 (주식·장기채가 앞 · 나머지 쌍은 1.5px + 흐림으로 뒤로) ──
export function RollingCorrChart({ pairs }: { pairs: MacroCorrelations["pairs"] }) {
  const anim = useChartAnimation();
  const data = useMemo(() => {
    const len = pairs.length ? Math.max(...pairs.map((p) => p.series.length)) : 0;
    return Array.from({ length: len }, (_, i) => {
      const row: Record<string, string | number> = { t: pairs[0].series[i]?.t ?? "" };
      for (const p of pairs) { const v = p.series[i]?.corr; if (v != null) row[p.key] = v; }
      return row;
    });
  }, [pairs]);
  // 읽는 줄 — 쌍마다 그날의 상관(없는 날은 "없어요" — 0 으로 적지 않는다). 색 표식 = 선 색.
  const rows: ReadRow[] = data.map((row) => ({ head: String(row.t), cells: pairs.map((p, i) => ({
    key: p.key, label: p.label, text: typeof row[p.key] === "number" ? signed(row[p.key] as number) : "없습니다", color: catColor(i) })) }));
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  if (!pairs.length) return <div className="mc-empty-sm">롤링 상관을 그릴 자료 없음</div>;
  return (
    <ReadoutFrame id="rolling-corr" label="60일 롤링 상관 추이" headLabel="날짜" rows={rows} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }} onMouseMove={followChart(setIdx)}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" tick={AX} stroke="var(--tx-line)" minTickGap={32} />
          <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]} tick={AX} stroke="var(--tx-line)" width={36} />
          <Legend wrapperStyle={{ fontSize: 13 }} formatter={inkLegend} />
          <ReferenceLine y={0} stroke="var(--tx-mute)" strokeWidth={1} />
          {pairs.map((p, i) => (
            <Line key={p.key} type="monotone" dataKey={p.key} name={p.label}
              stroke={catColor(i)} strokeWidth={p.key === "SPY-TLT" ? MARK.line : MARK.quiet} strokeOpacity={p.key === "SPY-TLT" ? 1 : MARK.quietOpacity}
              dot={false} isAnimationActive={anim} />
          ))}
          {idx >= 0 && <ReferenceLine x={data[idx].t} {...CROSSHAIR} />}
        </LineChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

// ── AvgCorrChart — 모든 자산 쌍의 평균 상관(분산이 잘 되는지). 0.6 선은 화면이 그은 참고선(서버 판정 아님). ──
export function AvgCorrChart({ avg }: { avg: MacroCorrelations["avg_corr"] }) {
  const anim = useChartAnimation();
  const data = useMemo(() => avg.map((p) => ({ t: p.t, corr: p.corr })), [avg]);
  const rows: ReadRow[] = data.map((p) => ({ head: p.t, cells: [{ key: "corr", label: "평균 상관", text: Number(p.corr).toFixed(2) }] }));
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  if (!avg.length) return <div className="mc-empty-sm">평균 상관을 그릴 자료 없음</div>;
  const cur = idx >= 0 ? data[idx] : null;
  return (
    <ReadoutFrame id="avg-corr" label="모든 자산 쌍의 평균 상관" headLabel="날짜" rows={rows} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }} onMouseMove={followChart(setIdx)}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" tick={AX} stroke="var(--tx-line)" minTickGap={32} />
          <YAxis domain={[0, 1]} tick={AX} stroke="var(--tx-line)" width={36} />
          <ReferenceLine y={0.6} stroke="var(--tx-mute)" strokeDasharray="3 3" label={{ value: "참고선 0.6", position: "insideTopRight", fontSize: 12, fill: "var(--tx-sub)" }} />
          <Area type="monotone" dataKey="corr" stroke="var(--tx-blue)" strokeWidth={MARK.line} fill="var(--tx-blue)" fillOpacity={MARK.wash} isAnimationActive={anim} />
          {cur && <ReferenceLine x={cur.t} {...CROSSHAIR} />}
          {cur && <ReferenceDot x={cur.t} y={cur.corr} {...DOT} />}
        </AreaChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

// ── TimingHistory — 위험 선호도 추이. 60·40 선은 서버 라벨 규칙(위험 선호 ≥60 · 위험 회피 ≤40)과 같은 값 — 색 없이 글자로. ──
export function TimingHistory({ history }: { history: MacroTiming["history"] }) {
  const anim = useChartAnimation();
  const rows: ReadRow[] = history.map((h) => ({ head: h.t, cells: [{ key: "score", label: "위험 선호도", text: Number(h.score).toFixed(0) }] }));
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  if (!history.length) return <div className="mc-empty-sm">위험 선호도 추이를 그릴 자료 없음</div>;
  const cur = idx >= 0 ? history[idx] : null;
  return (
    <ReadoutFrame id="timing-history" label="위험 선호도 추이" headLabel="날짜" rows={rows} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={210}>
        <AreaChart data={history} margin={{ top: 8, right: 16, bottom: 4, left: 0 }} onMouseMove={followChart(setIdx)}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" tick={AX} stroke="var(--tx-line)" minTickGap={28} />
          <YAxis domain={[0, 100]} ticks={[0, 40, 60, 100]} tick={AX} stroke="var(--tx-line)" width={36} />
          <ReferenceLine y={60} stroke="var(--tx-mute)" strokeDasharray="3 3" label={{ value: "위험 선호(60 이상)", position: "insideBottomLeft", fontSize: 12, fill: "var(--tx-sub)" }} />
          <ReferenceLine y={40} stroke="var(--tx-mute)" strokeDasharray="3 3" label={{ value: "위험 회피(40 이하)", position: "insideTopLeft", fontSize: 12, fill: "var(--tx-sub)" }} />
          <Area type="monotone" dataKey="score" stroke="var(--tx-blue)" strokeWidth={MARK.line} fill="var(--tx-blue)" fillOpacity={MARK.wash} isAnimationActive={anim} />
          {cur && <ReferenceLine x={cur.t} {...CROSSHAIR} />}
          {cur && <ReferenceDot x={cur.t} y={cur.score} {...DOT} />}
        </AreaChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

// ── RegimeTrajectory — 국면 궤적(경로) 산점도 ──
export function RegimeTrajectory({ path }: { path: TrajectoryPoint[] }) {
  // BU5b-1: 국면 바탕 = 국면 색(`--mc-q-*`, 도넛과 같은 네 색) · 사분면 이름 한국어 · 길은 한 계열 강조색 · 지금 점은 잉크.
  const anim = useChartAnimation();
  const data = useMemo(() => path.map((p) => ({ x: p.growth, y: p.inflation, t: p.t })), [path]);
  // 읽는 줄 — 달마다 성장·물가 점수와 그 달의 국면 이름(서버 `quadrant` 를 한국어로). 처음 자리 = 지금(마지막 달).
  const rows: ReadRow[] = path.map((p) => ({ head: p.t, cells: [
    { key: "g", label: "성장", text: Number(p.growth).toFixed(2) }, { key: "i", label: "물가", text: Number(p.inflation).toFixed(2) },
    { key: "q", label: "국면", text: regimeName(p.quadrant) },
  ] }));
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  if (!path.length) return <div className="mc-empty-sm">궤적을 그릴 관측 없음</div>;
  const last = data[data.length - 1];
  const cur = idx >= 0 && idx < data.length - 1 ? data[idx] : null;      // 지금(마지막) 점은 이미 잉크 점으로 보인다 — 다른 달을 고르면 고리
  // 동적 스케일 — 궤적 전체가 축 안에 들어오도록.
  const lim = Math.max(1, Math.ceil(Math.max(...data.map((d) => Math.max(Math.abs(d.x), Math.abs(d.y))))));
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim];
  const AX = { fontSize: 12, fill: "var(--tx-sub)" } as const;
  return (
    <ReadoutFrame id="regime-trajectory" label={`국면 궤적 ${data.length}개월`} headLabel="달" rows={rows} idx={idx} onKeyDown={onKeyDown}>
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
            <Scatter data={data} line={{ stroke: "var(--tx-blue)", strokeWidth: MARK.quiet }} lineType="joint"
              fill="var(--tx-blue)" fillOpacity={0.5} isAnimationActive={anim} onMouseEnter={(_: unknown, i: number) => setIdx(i)} />
            <ReferenceDot x={last.x} y={last.y} r={14} fill="var(--tx-ink)" fillOpacity={0.1} stroke="none" />
            <ReferenceDot x={last.x} y={last.y} r={5} fill="var(--tx-ink)" stroke="var(--tx-surface)" strokeWidth={2} />
            {cur && <ReferenceDot x={cur.x} y={cur.y} r={7} fill="none" stroke="var(--tx-ink)" strokeWidth={1.5} />}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </ReadoutFrame>
  );
}
