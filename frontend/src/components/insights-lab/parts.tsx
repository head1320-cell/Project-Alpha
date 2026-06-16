"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// insights-lab/parts — 후보 공용 비주얼 (recharts + SVG). 라이트 터미널 토큰 사용.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from "recharts";
import type { CompanyData, FactorVal, FactorGroup, ModelResult, Scenario, Tone } from "./sampleData";
import { won, eok, pct, toneColor, pctColor } from "./sampleData";

const ACCENT = "#1200ff", BULL = "#16a34a", BEAR = "#dc2626", MUTED = "#71717a", BORDER = "#e5e5e5";

// ── verdict 배지 ──
export function VerdictBadge({ verdict, tone, big }: { verdict: string; tone: Tone; big?: boolean }) {
  const c = toneColor(tone);
  return (
    <span className={`ca-verdict${big ? " big" : ""}`} style={{ color: c, borderColor: c, background: `color-mix(in srgb, ${c} 9%, transparent)` }}>
      {verdict}
    </span>
  );
}

// ── 반원 게이지 (0~100 점수 / 또는 임의 비율) ──
export function Gauge({ value, label, sub, color = ACCENT, size = 132 }: { value: number; label?: string; sub?: string; color?: string; size?: number }) {
  const v = Math.max(0, Math.min(100, value));
  const w = size, h = size * 0.62;
  return (
    <div className="ca-gauge" style={{ width: w }}>
      <svg viewBox="0 0 120 70" width={w} height={h}>
        <path d="M 10 62 A 50 50 0 0 1 110 62" fill="none" stroke="#ececef" strokeWidth="10" strokeLinecap="round" pathLength={100} />
        <path d="M 10 62 A 50 50 0 0 1 110 62" fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" pathLength={100} strokeDasharray={`${v} 100`} />
        <text x="60" y="54" textAnchor="middle" className="ca-gauge-num" style={{ fill: color }}>{Math.round(value)}</text>
      </svg>
      {label && <div className="ca-gauge-label">{label}</div>}
      {sub && <div className="ca-gauge-sub">{sub}</div>}
    </div>
  );
}

// ── 원형 점수 링 ──
export function ScoreRing({ score, size = 84 }: { score: number; size?: number }) {
  const c = score >= 66 ? BULL : score <= 40 ? BEAR : "#d97706";
  return (
    <div className="ca-ring" style={{ width: size, height: size }}>
      <svg viewBox="0 0 80 80" width={size} height={size}>
        <circle cx="40" cy="40" r="34" fill="none" stroke="#ececef" strokeWidth="7" />
        <circle cx="40" cy="40" r="34" fill="none" stroke={c} strokeWidth="7" strokeLinecap="round" pathLength={100} strokeDasharray={`${score} 100`} transform="rotate(-90 40 40)" />
        <text x="40" y="45" textAnchor="middle" className="ca-ring-num" style={{ fill: c }}>{score}</text>
      </svg>
    </div>
  );
}

// ── 주가 차트 (recharts Area) ──
export function PriceChart({ data, tone = "neutral", height = 220, intrinsic }: { data: CompanyData["price1y"]; tone?: Tone; height?: number; intrinsic?: number }) {
  const stroke = tone === "bull" ? BULL : tone === "bear" ? BEAR : ACCENT;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`cg-${tone}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.18} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="t" tick={{ fontSize: 10, fill: MUTED, fontFamily: "var(--t-mono)" }} interval={11} tickLine={false} axisLine={{ stroke: BORDER }} />
        <YAxis domain={["dataMin", "dataMax"]} tick={{ fontSize: 10, fill: MUTED, fontFamily: "var(--t-mono)" }} tickFormatter={(v) => (v / 1000).toFixed(0) + "k"} width={34} tickLine={false} axisLine={false} />
        <Tooltip formatter={(v: number) => [won(v), "종가"]} labelStyle={{ fontFamily: "var(--t-mono)", fontSize: 11 }} contentStyle={{ fontFamily: "var(--t-mono)", fontSize: 11, borderRadius: 2, border: `1px solid ${BORDER}` }} />
        {intrinsic && <ReferenceLine y={intrinsic} stroke={ACCENT} strokeDasharray="4 3" strokeWidth={1} label={{ value: `내재 ${won(intrinsic)}`, position: "insideTopRight", fontSize: 10, fill: ACCENT }} />}
        <Area type="monotone" dataKey="p" stroke={stroke} strokeWidth={1.6} fill={`url(#cg-${tone})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── KPI 막대 (매출/영업익/순익 추세) ──
export function KpiBars({ data, dataKey, color = ACCENT, height = 130, fmt = eok }: { data: CompanyData["years"]; dataKey: string; color?: string; height?: number; fmt?: (n: number) => string }) {
  const num = (d: CompanyData["years"][number]) => d[dataKey as keyof typeof d] as number;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data as unknown[]} margin={{ top: 14, right: 4, bottom: 0, left: 4 }}>
        <XAxis dataKey="year" tick={{ fontSize: 10, fill: MUTED, fontFamily: "var(--t-mono)" }} tickLine={false} axisLine={{ stroke: BORDER }} />
        <Tooltip formatter={(v: number) => [fmt(v), ""]} contentStyle={{ fontFamily: "var(--t-mono)", fontSize: 11, borderRadius: 2, border: `1px solid ${BORDER}` }} cursor={{ fill: "rgba(18,0,255,0.04)" }} />
        <Bar dataKey={dataKey} radius={[2, 2, 0, 0]}>
          {data.map((d, i) => <Cell key={i} fill={num(d) < 0 ? BEAR : i === data.length - 1 ? color : "#c7c7cf"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── 인라인 스파크라인 (테이블/카드용, 순수 SVG) ──
export function Spark({ values, color = ACCENT, w = 90, h = 26 }: { values: number[]; color?: string; w?: number; h?: number }) {
  if (!values.length) return null;
  const min = Math.min(...values), max = Math.max(...values), span = (max - min) || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - min) / span) * (h - 4)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={w} height={h} className="ca-spark">
      <polyline points={pts} fill="none" stroke={color === ACCENT ? (up ? BULL : BEAR) : color} strokeWidth="1.4" />
    </svg>
  );
}

// ── 내재가치 밴드 (현재가 vs RIM/DCF/DDM) ──
export function ValueBand({ price, models, intrinsic }: { price: number; models: ModelResult[]; intrinsic: number }) {
  const vals = [price, intrinsic, ...models.map((m) => m.value)];
  const lo = Math.min(...vals) * 0.96, hi = Math.max(...vals) * 1.04, span = hi - lo;
  const x = (v: number) => `${((v - lo) / span) * 100}%`;
  return (
    <div className="ca-band">
      <div className="ca-band-track">
        <div className="ca-band-fill" style={{ left: x(Math.min(price, intrinsic)), right: `${100 - ((Math.max(price, intrinsic) - lo) / span) * 100}%` }} />
        {models.map((m) => (
          <div key={m.key} className="ca-band-tick" style={{ left: x(m.value) }} title={`${m.key} ${won(m.value)}`}>
            <span className="ca-band-tick-dot" /><span className="ca-band-tick-lbl">{m.key}</span>
          </div>
        ))}
        <div className="ca-band-marker price" style={{ left: x(price) }}><span className="ca-band-marker-lbl">현재가<br />{won(price)}</span></div>
        <div className="ca-band-marker intrinsic" style={{ left: x(intrinsic) }}><span className="ca-band-marker-lbl up">내재가치<br />{won(intrinsic)}</span></div>
      </div>
      <div className="ca-band-axis"><span>{won(lo)}</span><span>{won(hi)}</span></div>
    </div>
  );
}

// ── 팩터 퍼센타일 바 ──
export function FactorBar({ fac, showPct = true }: { fac: FactorVal; showPct?: boolean }) {
  const c = pctColor(fac.pct);
  const valStr = fac.unit === "원" || fac.unit === "억" ? (fac.unit === "억" ? eok(fac.value) : won(fac.value)) : `${fac.value.toLocaleString()}${fac.unit}`;
  return (
    <div className="ca-fbar">
      <span className="ca-fbar-lbl">{fac.label}</span>
      <span className="ca-fbar-val">{valStr}</span>
      <span className="ca-fbar-track"><span className="ca-fbar-fill" style={{ width: `${fac.pct}%`, background: c }} /></span>
      {showPct && <span className="ca-fbar-pct" style={{ color: c }}>{fac.pct}</span>}
    </div>
  );
}

// ── 5각 레이더 (카테고리 평균 퍼센타일) ──
export function Radar({ groups, size = 240 }: { groups: FactorGroup[]; size?: number }) {
  const n = groups.length, cx = size / 2, cy = size / 2, R = size / 2 - 34;
  const avg = groups.map((g) => g.factors.reduce((s, x) => s + x.pct, 0) / g.factors.length);
  const pt = (i: number, r: number) => {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  const poly = avg.map((v, i) => pt(i, (v / 100) * R).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} className="ca-radar">
      {[0.25, 0.5, 0.75, 1].map((rr, k) => (
        <polygon key={k} points={groups.map((_, i) => pt(i, R * rr).join(",")).join(" ")} fill="none" stroke="#ececef" strokeWidth="1" />
      ))}
      {groups.map((_, i) => { const [x, y] = pt(i, R); return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#ececef" strokeWidth="1" />; })}
      <polygon points={poly} fill="rgba(18,0,255,0.12)" stroke={ACCENT} strokeWidth="1.6" />
      {avg.map((v, i) => { const [x, y] = pt(i, (v / 100) * R); return <circle key={i} cx={x} cy={y} r="2.6" fill={ACCENT} />; })}
      {groups.map((g, i) => { const [x, y] = pt(i, R + 16); return <text key={i} x={x} y={y} textAnchor="middle" className="ca-radar-lbl">{g.label.split("·")[0]}</text>; })}
    </svg>
  );
}

// ── Bull/Base/Bear 시나리오 카드 ──
export function ScenarioCards({ scenarios, price }: { scenarios: Scenario[]; price: number }) {
  const tone = (k: string): Tone => k === "bull" ? "bull" : k === "bear" ? "bear" : "neutral";
  return (
    <div className="ca-scen">
      {scenarios.map((s) => {
        const c = toneColor(tone(s.key));
        return (
          <div key={s.key} className={`ca-scen-card ${s.key}`}>
            <div className="ca-scen-head" style={{ color: c }}>{s.label}</div>
            <div className="ca-scen-val">{won(s.value)}</div>
            <div className="ca-scen-gap" style={{ color: c }}>{pct(s.gap)} <span className="ca-scen-vs">vs 현재가</span></div>
            <div className="ca-scen-note">{s.note}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── 작은 KPI 셀 (라벨/값/서브) ──
export function Metric({ label, value, sub, color }: { label: string; value: React.ReactNode; sub?: React.ReactNode; color?: string }) {
  return (
    <div className="ca-metric">
      <span className="ca-metric-lbl">{label}</span>
      <span className="ca-metric-val" style={color ? { color } : undefined}>{value}</span>
      {sub != null && <span className="ca-metric-sub">{sub}</span>}
    </div>
  );
}

export { won, eok, pct };
