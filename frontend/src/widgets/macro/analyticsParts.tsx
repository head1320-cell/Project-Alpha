"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// analyticsParts — 상관 · 타이밍 · 국면 궤적 그림 (recharts + SVG)
//   CorrMatrix · RollingCorrChart · AvgCorrChart · ComponentBars · TimingHistory · TrendTable · RegimeTrajectory.
// BU5b-2: 상관 = 수준 양쪽 색(주황 같이 움직임 / 청록 반대로) · 상관 선 = 범주색 · 점수(신호·종합) = 중립(판단은 글자) ·
//   가격 방향(이동평균 대비·12개월 모멘텀·추세) = 등락색 + 부호 · 툴팁 대신 읽기 줄 · 그림은 하나도 지우지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, ScatterChart, Scatter,
  ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import type { MacroCorrelations, MacroTiming, TimingComponent, TrajectoryPoint, TrendRow } from "@/entities/macro/analysisModel";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { regimeName } from "@/entities/macro/regimeKo";
import { TIP_STYLE, moveColor } from "./cockpitParts";
import { catColor, signed } from "./macroKo";

const AX = { fontSize: 11, fill: "var(--tx-sub)" } as const;
/** 상관(−1..+1) → 칸 바탕. |c| 0.2·0.4·0.7 경계로 쪽마다 3 단 — 그리기 위한 구간이지 판단이 아니다(값은 늘 글자로). */
export function corrFill(c: number | null | undefined): string {
  if (c == null || !Number.isFinite(c)) return "var(--mc-lv-none)";
  const a = Math.abs(c);
  if (a < 0.2) return "var(--mc-lv-mid)";
  const k = a < 0.4 ? 1 : a < 0.7 ? 2 : 3;
  return `var(--mc-lv-${c > 0 ? "pos" : "neg"}-${k})`;
}
/** 범례 글자를 선 색이 아니라 잉크로 — 노랑·분홍 선 색 글자는 AA 를 떨어뜨린다(BU4 에서 배운 것). */
const inkLegend = (v: string) => <span style={{ color: "var(--tx-ink)" }}>{v}</span>;

// ── CorrMatrix — N×N 상관 지도. 줄에 초점(Tab)·칸에 올림 → 아래 읽기 줄 ──
export function CorrMatrix({ m }: { m: MacroCorrelations["matrix"] }) {
  const [cur, setCur] = useState<string | null>(null);
  const n = m.tickers.length;
  if (!n) return <div className="mc-empty-sm">상관을 잴 자산이 없어요</div>;
  const name = (i: number) => `${m.labels[i] ?? m.tickers[i]}(${m.tickers[i]})`;
  const say = (i: number, j: number) => `${name(i)} · ${name(j)} · ${signed(m.values[i][j])}`;
  /** 줄에 초점 → 그 자산과 가장 같이·가장 반대로 움직인 자산(자기 자신 제외). */
  const rowSay = (i: number) => {
    const others = m.values[i].map((v, j) => [v, j] as const).filter(([, j]) => j !== i);
    if (!others.length) return name(i);
    const hi = others.reduce((a, b) => (b[0] > a[0] ? b : a)), lo = others.reduce((a, b) => (b[0] < a[0] ? b : a));
    return `${name(i)} · 가장 같이 움직인 ${name(hi[1])} ${signed(hi[0])} · 가장 반대로 움직인 ${name(lo[1])} ${signed(lo[0])}`;
  };
  return (
    <div className="mc-matrix-wrap">
      <div className="mc-tablewrap">
        <div className="mca-matrix" style={{ gridTemplateColumns: `52px repeat(${n}, minmax(30px, 1fr))` }}>
          <div className="mca-mx-corner" />
          {m.tickers.map((t) => <div key={`h${t}`} className="mca-mx-head" data-mono>{t}</div>)}
          {m.tickers.map((row, i) => (
            <React.Fragment key={`r${row}`}>
              <div className="mca-mx-row" data-mono tabIndex={0} aria-label={`${name(i)} 줄`} onFocus={() => setCur(rowSay(i))}>{row}</div>
              {m.values[i].map((v, j) => (
                <div key={`${i}-${j}`} className="mca-mx-cell" style={{ background: corrFill(v) }} onMouseEnter={() => setCur(say(i, j))}>
                  {i === j ? "" : v.toFixed(2).replace(/^0/, "").replace(/^-0/, "−")}
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </div>
      <div className="mc-zlegend"><span>반대로 움직여요</span><i className="mc-zleg-grad" aria-hidden /><span>같이 움직여요</span></div>
      <p className="mc-readout" aria-live="polite">{cur ?? "칸에 마우스를 올리거나 줄을 Tab 으로 고르면 여기에 두 자산과 상관이 나와요"}</p>
    </div>
  );
}

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

// ── ComponentBars — 타이밍 신호별 점수(0~100). 막대는 중립 — 점수가 높고 낮음을 색으로 판단하지 않는다. ──
export function ComponentBars({ comps }: { comps: TimingComponent[] }) {
  return (
    <div className="mca-comps">
      {comps.map((c) => (
        <div key={c.key} className="mca-comp">
          <span className="mca-comp-lbl"><span data-server>{c.label}</span><em>가중 {c.weight}</em></span>
          <div className="mca-comp-track" aria-hidden><i style={{ width: `${Math.max(2, Math.min(100, c.score))}%` }} /></div>
          <span className="mca-comp-sc">{c.score.toFixed(0)}</span>
          <span className="mca-comp-val">{c.value != null ? c.value : "몰라요"}</span>
        </div>
      ))}
    </div>
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

// ── TrendTable — 자산별 추세 ──
// 가격 방향(이동평균 대비·12개월 모멘텀)은 등락색 + ▲▼ + 부호. 52주 고점 거리는 늘 0 이하라 색 없이 숫자. RSI 는 점 하나(잉크) — 30·70 구간 뜻은 열 머리 글자.
function PctCell({ v }: { v: number | null | undefined }) {
  if (v == null || !Number.isFinite(v)) return <td className="n">몰라요</td>;
  return (
    <td className="n" style={{ color: moveColor(v) }}>
      <span className="mca-arrow" aria-hidden>{v > 0 ? "▲" : v < 0 ? "▼" : ""}</span> {signed(v, 1)}%
    </td>
  );
}
/** 추세 글자(서버) → 등락 방향. 모르는 글자는 중립. */
const TREND_DIR: Record<string, "up" | "down"> = { "상승": "up", "하락": "down" };

export function TrendTable({ assets }: { assets: TrendRow[] }) {
  return (
    <div className="mc-tablewrap">
      <table className="mca-trend v2">
        <thead><tr><th>자산</th><th className="n">200일선 대비</th><th className="n">12개월 모멘텀</th><th className="n">52주 고점까지</th><th className="n">RSI(30 아래 과매도 · 70 위 과매수)</th><th>추세</th></tr></thead>
        <tbody>
          {assets.map((a) => {
            const dir = TREND_DIR[a.trend];
            const rsi = a.rsi;
            return (
              <tr key={a.ticker}>
                <td><b data-mono>{a.ticker}</b> <span className="mca-trend-nm">{a.label}</span></td>
                <PctCell v={a.vs_ma200_pct} />
                <PctCell v={a.mom_12m} />
                <td className="n">{a.dist_52w_high == null ? "몰라요" : `${signed(a.dist_52w_high, 1)}%`}</td>
                <td className="n">
                  {rsi != null ? (
                    <span className="mca-rsi">
                      <span className="mca-rsi-track" aria-hidden>
                        <i className="mca-rsi-zone" />
                        <i className="mca-rsi-dot" style={{ left: `${Math.max(0, Math.min(100, rsi))}%` }} />
                      </span>
                      {rsi.toFixed(0)}
                    </span>
                  ) : "몰라요"}
                </td>
                <td><span className="mca-trend-pill" data-dir={dir ?? "flat"} style={{ color: dir === "up" ? "var(--tx-up-ink)" : dir === "down" ? "var(--tx-down-ink)" : "var(--tx-ink)" }}>
                  {dir === "up" ? "▲ " : dir === "down" ? "▼ " : ""}{a.trend}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
