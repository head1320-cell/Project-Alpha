"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// analyticsParts — 상관/타이밍/국면궤적 시각화 (recharts + SVG)
//   CorrMatrix · RollingCorrChart · AvgCorrChart · ComponentBars · TimingHistory ·
//   TrendTable · RegimeTrajectory. "Institutional Terminal" 토큰.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, ScatterChart, Scatter,
  ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import type { MacroCorrelations, MacroTiming, TimingComponent, TrendRow, TrajectoryPoint } from "@/lib/screenerApi";

const TIP = { background: "#fff", border: "1px solid var(--t-border)", borderRadius: 2, fontSize: 11, fontFamily: "var(--t-mono, monospace)" };
const PAIR_COLORS: Record<string, string> = {
  "SPY-TLT": "#1200ff", "SPY-GLD": "#a16207", "SPY-PDBC": "#ea580c", "SPY-EEM": "#0891b2", "SPY-HYG": "#dc2626",
};
const fmt1 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}`);

// 상관 발산색 (−1 청 / +1 적)
export function corrFill(c: number | null | undefined): string {
  if (c == null || !Number.isFinite(c)) return "rgba(113,113,122,0.06)";
  const t = Math.max(-1, Math.min(1, c));
  const a = 0.1 + 0.72 * Math.abs(t);
  return t >= 0 ? `rgba(220,38,38,${a.toFixed(3)})` : `rgba(37,99,235,${a.toFixed(3)})`;
}
function scoreColor(s: number): string {
  if (s >= 60) return "var(--color-bull)";
  if (s <= 40) return "var(--color-bear)";
  return "var(--color-caution)";
}
function trendColor(t: string): string {
  return t === "상승" ? "var(--color-bull)" : t === "하락" ? "var(--color-bear)" : "var(--t-muted)";
}

// ── CorrMatrix — N×N 상관 히트맵 ──
export function CorrMatrix({ m }: { m: MacroCorrelations["matrix"] }) {
  const n = m.tickers.length;
  if (!n) return <div className="mc-empty-sm">상관 데이터 없음</div>;
  return (
    <div className="mca-matrix" style={{ gridTemplateColumns: `48px repeat(${n}, 1fr)` }}>
      <div className="mca-mx-corner" />
      {m.tickers.map((t) => <div key={`h${t}`} className="mca-mx-head">{t}</div>)}
      {m.tickers.map((row, i) => (
        <React.Fragment key={`r${row}`}>
          <div className="mca-mx-row" title={m.labels[i]}>{row}</div>
          {m.values[i].map((v, j) => (
            <div key={`${i}-${j}`} className="mca-mx-cell" style={{ background: corrFill(v) }}
              title={`${m.tickers[i]} · ${m.tickers[j]}: ${v.toFixed(2)}`}>
              {i === j ? "" : v.toFixed(2).replace(/^0/, "").replace(/^-0/, "-")}
            </div>
          ))}
        </React.Fragment>
      ))}
    </div>
  );
}

// ── RollingCorrChart — 롤링 상관 추이 (주식-채권 강조) ──
export function RollingCorrChart({ pairs }: { pairs: MacroCorrelations["pairs"] }) {
  if (!pairs.length) return <div className="mc-empty-sm">롤링 상관 데이터 없음</div>;
  const len = Math.max(...pairs.map((p) => p.series.length));
  const data = Array.from({ length: len }, (_, i) => {
    const row: Record<string, string | number> = { t: pairs[0].series[i]?.t ?? "" };
    for (const p of pairs) { const v = p.series[i]?.corr; if (v != null) row[p.key] = v; }
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" minTickGap={32} />
        <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]} tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" width={36} />
        <Tooltip contentStyle={TIP} />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <ReferenceLine y={0} stroke="var(--t-ink)" strokeWidth={1} />
        {pairs.map((p) => (
          <Line key={p.key} type="monotone" dataKey={p.key} name={p.label}
            stroke={PAIR_COLORS[p.key] ?? "#64748b"} strokeWidth={p.key === "SPY-TLT" ? 2.4 : 1.2}
            dot={false} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── AvgCorrChart — 평균 페어상관(분산 국면) ──
export function AvgCorrChart({ avg }: { avg: MacroCorrelations["avg_corr"] }) {
  if (!avg.length) return <div className="mc-empty-sm">평균 상관 데이터 없음</div>;
  const data = avg.map((p) => ({ t: p.t, corr: p.corr }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
        <defs><linearGradient id="mcaAvg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#dc2626" stopOpacity={0.28} /><stop offset="100%" stopColor="#dc2626" stopOpacity={0.03} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" minTickGap={32} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" width={36} />
        <Tooltip contentStyle={TIP} />
        <ReferenceArea y1={0.6} y2={1} fill="rgba(220,38,38,0.06)" stroke="none" />
        <ReferenceLine y={0.6} stroke="var(--color-bear)" strokeDasharray="3 3" label={{ value: "상관 붕괴 위험", position: "insideTopRight", fontSize: 9, fill: "var(--color-bear)" }} />
        <Area type="monotone" dataKey="corr" stroke="#dc2626" strokeWidth={1.6} fill="url(#mcaAvg)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── ComponentBars — 타이밍 신호별 기여 ──
export function ComponentBars({ comps }: { comps: TimingComponent[] }) {
  return (
    <div className="mca-comps">
      {comps.map((c) => (
        <div key={c.key} className="mca-comp">
          <span className="mca-comp-lbl">{c.label}<em>w{c.weight}</em></span>
          <div className="mca-comp-track"><i style={{ width: `${Math.max(2, Math.min(100, c.score))}%`, background: scoreColor(c.score) }} /></div>
          <span className="mca-comp-sc" style={{ color: scoreColor(c.score) }}>{c.score.toFixed(0)}</span>
          <span className="mca-comp-val">{c.value != null ? c.value : "—"}</span>
        </div>
      ))}
    </div>
  );
}

// ── TimingHistory — 종합점수 추이 + 온/오프 임계 ──
export function TimingHistory({ history }: { history: MacroTiming["history"] }) {
  if (!history.length) return <div className="mc-empty-sm">타이밍 추이 데이터 없음</div>;
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={history} margin={{ top: 8, right: 16, bottom: 4, left: -16 }}>
        <defs><linearGradient id="mcaTim" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--t-accent)" stopOpacity={0.25} /><stop offset="100%" stopColor="var(--t-accent)" stopOpacity={0.02} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" minTickGap={28} />
        <YAxis domain={[0, 100]} ticks={[0, 40, 60, 100]} tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" width={32} />
        <Tooltip contentStyle={TIP} />
        <ReferenceArea y1={60} y2={100} fill="rgba(22,163,74,0.05)" stroke="none" />
        <ReferenceArea y1={0} y2={40} fill="rgba(220,38,38,0.05)" stroke="none" />
        <ReferenceLine y={60} stroke="var(--color-bull)" strokeDasharray="3 3" />
        <ReferenceLine y={40} stroke="var(--color-bear)" strokeDasharray="3 3" />
        <Area type="monotone" dataKey="score" stroke="var(--t-accent)" strokeWidth={1.8} fill="url(#mcaTim)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── TrendTable — 자산별 추세 상태 ──
// 조건부 서식 셀 — ▲/▼ 화살표 + 옅은 배경 틴트 (Gemini UI 개편 2순위: 테이블의 꽃)
function PctCell({ v }: { v: number | null | undefined }) {
  if (v == null) return <td className="n">—</td>;
  const up = v >= 0;
  return (
    <td className="n" style={{
      color: up ? "var(--color-bull)" : "var(--color-bear)",
      background: up ? "rgba(22,163,74,.06)" : "rgba(220,38,38,.05)",
    }}>
      <span className="mca-arrow">{up ? "▲" : "▼"}</span> {up ? "+" : ""}{v.toFixed(1)}%
    </td>
  );
}

const TREND_PILL: Record<string, { fg: string; bg: string }> = {
  "상승": { fg: "#0e7c4a", bg: "rgba(22,163,74,.12)" },
  "하락": { fg: "#b91c1c", bg: "rgba(220,38,38,.10)" },
  "중립": { fg: "#71717a", bg: "rgba(113,113,122,.10)" },
};

export function TrendTable({ assets }: { assets: TrendRow[] }) {
  return (
    <table className="mca-trend v2">
      <thead><tr><th>자산</th><th className="n">200일선 대비</th><th className="n">12M 모멘텀</th><th className="n">52주高 거리</th><th className="n">RSI</th><th>추세</th></tr></thead>
      <tbody>
        {assets.map((a) => {
          const pill = TREND_PILL[a.trend] ?? TREND_PILL["중립"];
          const rsi = a.rsi;
          return (
            <tr key={a.ticker}>
              <td><b>{a.ticker}</b> <span className="mca-trend-nm">{a.label}</span></td>
              <PctCell v={a.vs_ma200_pct} />
              <PctCell v={a.mom_12m} />
              <td className="n" style={{ color: (a.dist_52w_high ?? 0) > -3 ? "var(--color-bull)" : "var(--t-muted)" }}>{fmt1(a.dist_52w_high)}%</td>
              <td className="n">
                {rsi != null ? (
                  <span className="mca-rsi" title={`RSI ${rsi.toFixed(0)} (30 과매도 · 70 과매수)`}>
                    <span className="mca-rsi-track">
                      <i className="mca-rsi-zone" />
                      <i className="mca-rsi-dot" style={{ left: `${Math.max(0, Math.min(100, rsi))}%`,
                        background: rsi >= 70 ? "#dc2626" : rsi <= 30 ? "#2563eb" : "#71717a" }} />
                    </span>
                    {rsi.toFixed(0)}
                  </span>
                ) : "—"}
              </td>
              <td><span className="mca-trend-pill" style={{ color: pill.fg, background: pill.bg }}>{a.trend}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── RegimeTrajectory — 국면 궤적(경로) 산점도 ──
export function RegimeTrajectory({ path }: { path: TrajectoryPoint[] }) {
  if (!path.length) return <div className="mc-empty-sm">궤적 데이터 없음</div>;
  const data = path.map((p) => ({ x: p.growth, y: p.inflation, t: p.t }));
  const last = data[data.length - 1];
  // ★동적 스케일(CIO §2) — 궤적 전체가 축 안에 들어오도록. 라벨 통일 명명.
  const lim = Math.max(1, Math.ceil(Math.max(...data.map((d) => Math.max(Math.abs(d.x), Math.abs(d.y))))));
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim];
  return (
    <div className="mc-scatter">
      <span className="mc-quad tr">REFLATION<em>성장↑·물가↑</em></span>
      <span className="mc-quad tl">STAGFLATION<em>성장↓·물가↑</em></span>
      <span className="mc-quad br">GOLDILOCKS<em>성장↑·물가↓</em></span>
      <span className="mc-quad bl">DISINFLATION<em>성장↓·물가↓</em></span>
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 14, right: 18, bottom: 22, left: 6 }}>
          <ReferenceArea x1={0} x2={lim} y1={-lim} y2={0} fill="rgba(22,163,74,0.06)" stroke="none" />
          <ReferenceArea x1={0} x2={lim} y1={0} y2={lim} fill="rgba(234,88,12,0.06)" stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={0} y2={lim} fill="rgba(220,38,38,0.06)" stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={-lim} y2={0} fill="rgba(37,99,235,0.06)" stroke="none" />
          <XAxis type="number" dataKey="x" domain={[-lim, lim]} ticks={ticks} tick={{ fontSize: 10, fill: "var(--t-muted)" }} stroke="var(--t-border)" label={{ value: "성장 →", position: "insideBottom", offset: -10, fontSize: 10, fill: "var(--t-muted)" }} />
          <YAxis type="number" dataKey="y" domain={[-lim, lim]} ticks={ticks} tick={{ fontSize: 10, fill: "var(--t-muted)" }} stroke="var(--t-border)" label={{ value: "물가 →", angle: -90, position: "insideLeft", fontSize: 10, fill: "var(--t-muted)" }} />
          <ReferenceLine x={0} stroke="var(--t-border)" />
          <ReferenceLine y={0} stroke="var(--t-border)" />
          <Tooltip contentStyle={TIP} cursor={{ strokeDasharray: "3 3" }} formatter={(v: number | string) => Number(v).toFixed(2)} />
          <Scatter data={data} line={{ stroke: "var(--t-accent)", strokeWidth: 1.5 }} lineType="joint"
            fill="var(--t-accent)" fillOpacity={0.45} isAnimationActive={false} />
          <ReferenceDot x={last.x} y={last.y} r={16} fill="var(--t-accent)" fillOpacity={0.14} stroke="none" />
          <ReferenceDot x={last.x} y={last.y} r={5} fill="var(--t-accent)" stroke="#fff" strokeWidth={1.5} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
