"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// cockpitParts — Macro Allocation Cockpit 시각화 프리미티브 (recharts + SVG)
//   RegimeScatter · CycleClock · ArcGauge · YieldCurveChart · Sparkline · ZBar ·
//   IndicatorCard · ZHeatmap · ValuationBars · HoldingsDonut · SignalBadge ·
//   CompositeRow · DrillDownModal. 전부 "Institutional Terminal" 토큰 사용.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, ScatterChart, Scatter,
  ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Tooltip,
  RadialBarChart, RadialBar, PolarAngleAxis, PieChart, Pie, Cell,
} from "recharts";
import { X } from "lucide-react";
import { zScoreColor, type YieldCurvePoint, type MacroSeries } from "@/entities/macro/api";
import type { MacroIndicator, MacroTheme, TacticalHolding } from "@/entities/macro";

// ── 포맷·색 helpers ──
export const fmtNum = (v: number | null | undefined, d = 2): string =>
  v == null || !Number.isFinite(v) ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(d);
export const fmtZ = (z: number | null | undefined): string => (z == null || !Number.isFinite(z) ? "—" : `${z >= 0 ? "+" : ""}${z.toFixed(2)}σ`);
export const fmtPct = (v: number | null | undefined, d = 1): string => (v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
export const clamp1 = (v: number): number => Math.max(-1, Math.min(1, v));
// 연속 발산 색 (−3..+3): 음수 파랑 / 양수 빨강 / 0 근처 옅음 (MacroMicro·Valley AI 히트맵 톤)
export function zFill(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "rgba(113,113,122,0.08)";
  const t = Math.max(-3, Math.min(3, z)) / 3;
  const a = 0.12 + 0.66 * Math.abs(t);
  return t >= 0 ? `rgba(220,38,38,${a.toFixed(3)})` : `rgba(37,99,235,${a.toFixed(3)})`;
}
export function sigColor(sig: string): string {
  if (sig.includes("공격")) return "var(--color-bull)";
  if (sig.includes("방어")) return "var(--color-bear)";
  return "var(--color-caution)";
}
const DONUT_COLORS = ["#1200ff", "#16a34a", "#ea580c", "#0891b2", "#a16207", "#7c3aed", "#dc2626", "#0d9488", "#c026d3", "#64748b"];
const TIP_STYLE = { background: "#fff", border: "1px solid var(--t-border)", borderRadius: 2, fontSize: 11, fontFamily: "var(--t-mono, monospace)" };

// ─────────────────────────────────────────────────────────────────────────────
// RegimeScatter — 성장(x) × 물가(y) 2D 산점도 + 4국면 배경 + 현재위치 글로우 마커
// ─────────────────────────────────────────────────────────────────────────────
export function RegimeScatter({ g, i }: { g: number; i: number }) {
  // ★동적 스케일(CIO §2): 축 한계를 데이터에 맞춰 확장 — 스코어 +2.06이 [-1,1] 고정축에
  //   클램프돼 마커가 안 보이던 버그 수정. 코너 라벨도 통일 명명(Reflation=성장↑·물가↑).
  const lim = Math.max(1, Math.ceil(Math.max(Math.abs(g), Math.abs(i))));
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim];
  const x = g, y = i;
  const pt = [{ x, y }];
  return (
    <div className="mc-scatter">
      <span className="mc-quad tr">REFLATION<em>성장↑·물가↑</em></span>
      <span className="mc-quad tl">STAGFLATION<em>성장↓·물가↑</em></span>
      <span className="mc-quad br">GOLDILOCKS<em>성장↑·물가↓</em></span>
      <span className="mc-quad bl">DISINFLATION<em>성장↓·물가↓</em></span>
      <ResponsiveContainer width="100%" height={340}>
        <ScatterChart margin={{ top: 14, right: 18, bottom: 22, left: 6 }}>
          <ReferenceArea x1={0} x2={lim} y1={-lim} y2={0} fill="rgba(22,163,74,0.07)" stroke="none" />
          <ReferenceArea x1={0} x2={lim} y1={0} y2={lim} fill="rgba(234,88,12,0.07)" stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={0} y2={lim} fill="rgba(220,38,38,0.07)" stroke="none" />
          <ReferenceArea x1={-lim} x2={0} y1={-lim} y2={0} fill="rgba(37,99,235,0.07)" stroke="none" />
          <XAxis type="number" dataKey="x" domain={[-lim, lim]} ticks={ticks} tick={{ fontSize: 10, fill: "var(--t-muted)" }} stroke="var(--t-border)" label={{ value: "성장 →", position: "insideBottom", offset: -10, fontSize: 10, fill: "var(--t-muted)" }} />
          <YAxis type="number" dataKey="y" domain={[-lim, lim]} ticks={ticks} tick={{ fontSize: 10, fill: "var(--t-muted)" }} stroke="var(--t-border)" label={{ value: "물가 →", angle: -90, position: "insideLeft", fontSize: 10, fill: "var(--t-muted)" }} />
          <ReferenceLine x={0} stroke="var(--t-border)" strokeWidth={1} />
          <ReferenceLine y={0} stroke="var(--t-border)" strokeWidth={1} />
          <ReferenceDot x={x} y={y} r={18} fill="var(--t-accent)" fillOpacity={0.12} stroke="none" />
          <ReferenceDot x={x} y={y} r={9} fill="var(--t-accent)" fillOpacity={0.32} stroke="none" />
          <ReferenceDot x={x} y={y} r={4.5} fill="var(--t-accent)" stroke="#fff" strokeWidth={1.5} />
          <Scatter data={pt} fill="var(--t-accent)" fillOpacity={0} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CycleClock — 경기순환 시계 (4국면 원형 배치 + 현재 위치 바늘)
//   각도: atan2(inflation, growth). Goldilocks(우하)→Reflation(우상)→Stagflation(좌상)→Disinflation(좌하)
// ─────────────────────────────────────────────────────────────────────────────
export function CycleClock({ g, i, size = 200 }: { g: number; i: number; size?: number }) {
  const cx = size / 2, cy = size / 2, R = size * 0.4;
  const ang = Math.atan2(clamp1(i), clamp1(g)); // 표준 수학각 (x우 y상)
  const nx = cx + R * Math.cos(ang), ny = cy - R * Math.sin(ang);
  const mag = Math.min(1, Math.hypot(clamp1(g), clamp1(i)));
  const sectors = [
    { a0: -45, a1: 45, fill: "rgba(234,88,12,0.10)", lbl: "REFLATE", lx: cx + R * 0.7, ly: cy - R * 0.62 },
    { a0: 45, a1: 135, fill: "rgba(220,38,38,0.10)", lbl: "STAGFLATE", lx: cx - R * 0.7, ly: cy - R * 0.62 },
    { a0: 135, a1: 225, fill: "rgba(37,99,235,0.10)", lbl: "DISINFLATE", lx: cx - R * 0.7, ly: cy + R * 0.72 },
    { a0: 225, a1: 315, fill: "rgba(22,163,74,0.10)", lbl: "GOLDILOCKS", lx: cx + R * 0.7, ly: cy + R * 0.72 },
  ];
  const arc = (a0: number, a1: number) => {
    const p0 = [cx + R * Math.cos((a0 * Math.PI) / 180), cy - R * Math.sin((a0 * Math.PI) / 180)];
    const p1 = [cx + R * Math.cos((a1 * Math.PI) / 180), cy - R * Math.sin((a1 * Math.PI) / 180)];
    return `M ${cx} ${cy} L ${p0[0].toFixed(1)} ${p0[1].toFixed(1)} A ${R} ${R} 0 0 0 ${p1[0].toFixed(1)} ${p1[1].toFixed(1)} Z`;
  };
  return (
    <svg width={size} height={size} className="mc-clock">
      {sectors.map((s) => <path key={s.lbl} d={arc(s.a0, s.a1)} fill={s.fill} stroke="var(--t-border)" strokeWidth={0.5} />)}
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="var(--t-border)" strokeWidth={1} />
      <line x1={cx - R} y1={cy} x2={cx + R} y2={cy} stroke="var(--t-border)" strokeWidth={0.5} strokeDasharray="2 2" />
      <line x1={cx} y1={cy - R} x2={cx} y2={cy + R} stroke="var(--t-border)" strokeWidth={0.5} strokeDasharray="2 2" />
      {sectors.map((s) => <text key={s.lbl + "t"} x={s.lx} y={s.ly} fontSize={8.5} fill="var(--t-muted)" textAnchor="middle" fontFamily="var(--t-mono, monospace)">{s.lbl}</text>)}
      <line x1={cx} y1={cy} x2={nx.toFixed(1)} y2={ny.toFixed(1)} stroke="var(--t-accent)" strokeWidth={2} />
      <circle cx={nx} cy={ny} r={6} fill="var(--t-accent)" fillOpacity={0.18} />
      <circle cx={nx} cy={ny} r={3.2} fill="var(--t-accent)" stroke="#fff" strokeWidth={1} />
      <circle cx={cx} cy={cy} r={3} fill="var(--t-ink)" />
      <text x={cx} y={cy + R + 14} fontSize={9} fill="var(--t-muted)" textAnchor="middle" fontFamily="var(--t-mono, monospace)">강도 {(mag * 100).toFixed(0)}%</text>
    </svg>
  );
}

// ── ArcGauge — 반원 게이지 (Stress·Fit 점수) ──
export function ArcGauge({ value, max = 100, color, label, sub, height = 132 }: { value: number; max?: number; color: string; label: string; sub?: string; height?: number }) {
  const v = Math.max(0, Math.min(max, value || 0));
  const data = [{ name: "v", value: v }];
  return (
    <div className="mc-gauge">
      <ResponsiveContainer width="100%" height={height}>
        <RadialBarChart innerRadius="66%" outerRadius="100%" data={data} startAngle={180} endAngle={0} barSize={13}>
          <PolarAngleAxis type="number" domain={[0, max]} tick={false} />
          <RadialBar background={{ fill: "var(--t-border)" }} dataKey="value" cornerRadius={7} fill={color} isAnimationActive={false} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="mc-gauge-c"><b style={{ color }}>{Math.round(v)}</b><span>{label}</span></div>
      {sub && <div className="mc-gauge-sub">{sub}</div>}
    </div>
  );
}

// ── YieldCurveChart — 미국 국채 수익률곡선 (3M~30Y) ──
export function YieldCurveChart({ points, inversion }: { points: YieldCurvePoint[]; inversion: boolean }) {
  const data = points.map((p) => ({ label: p.label, y: p.yield_pct }));
  const stroke = inversion ? "var(--color-bear)" : "var(--t-accent)";
  return (
    <ResponsiveContainer width="100%" height={210}>
      <LineChart data={data} margin={{ top: 12, right: 18, bottom: 4, left: -8 }}>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--t-muted)" }} stroke="var(--t-border)" />
        <YAxis tick={{ fontSize: 10, fill: "var(--t-muted)" }} stroke="var(--t-border)" domain={["auto", "auto"]} unit="%" width={44} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string) => [`${val}%`, "수익률"]} />
        <Line type="monotone" dataKey="y" stroke={stroke} strokeWidth={2} dot={{ r: 2.5, fill: stroke }} activeDot={{ r: 4 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Sparkline — 경량 SVG (지표카드용) ──
export function Sparkline({ values, w = 200, h = 30, color = "var(--t-accent)" }: { values: number[]; w?: number; h?: number; color?: string }) {
  const vals = (values || []).filter((v) => Number.isFinite(v));
  if (vals.length < 2) return <svg width={w} height={h} className="mc-spark" />;
  const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
  const step = w / (vals.length - 1);
  const pts = vals.map((v, idx) => `${(idx * step).toFixed(1)},${(h - ((v - min) / range) * (h - 4) - 2).toFixed(1)}`).join(" ");
  const c = color === "auto" ? (vals[vals.length - 1] >= vals[0] ? "var(--color-bull)" : "var(--color-bear)") : color;
  return <svg width={w} height={h} className="mc-spark" preserveAspectRatio="none" viewBox={`0 0 ${w} ${h}`}><polyline points={pts} fill="none" stroke={c} strokeWidth={1.4} /></svg>;
}

// ── ZBar — z-score 막대 (중앙 0, −3..+3) ──
export function ZBar({ z }: { z: number | null | undefined }) {
  const v = z == null || !Number.isFinite(z) ? 0 : Math.max(-3, Math.min(3, z));
  const w = (Math.abs(v) / 3) * 50;
  return (
    <div className="mc-zbar">
      <div className="mc-zbar-mid" />
      <div className="mc-zbar-fill" style={{ width: `${w}%`, background: zScoreColor(z ?? null), ...(v >= 0 ? { left: "50%" } : { right: "50%" }) }} />
    </div>
  );
}

// ── IndicatorCard — 지표 카드 (클릭 → 드릴다운) ──
export function IndicatorCard({ ind, onClick }: { ind: MacroIndicator; onClick?: () => void }) {
  return (
    <button className="mc-ind" onClick={onClick}>
      <div className="mc-ind-h"><span className="mc-ind-nm">{ind.name}</span><span className="mc-ind-z" style={{ color: zScoreColor(ind.z_score) }}>{fmtZ(ind.z_score)}</span></div>
      <div className="mc-ind-v">
        <b>{fmtNum(ind.latest)}</b><em>{ind.unit}</em>
        {ind.delta != null && Number.isFinite(ind.delta) && <span className="mc-ind-d" style={{ color: ind.delta >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{ind.delta >= 0 ? "▲" : "▼"} {fmtNum(Math.abs(ind.delta))}</span>}
      </div>
      <Sparkline values={ind.spark} w={210} h={28} color="auto" />
      <div className="mc-ind-pct"><i style={{ width: `${Math.max(2, Math.min(100, ind.percentile ?? 50))}%` }} /></div>
      <span className="mc-ind-pctlbl">{ind.percentile != null ? `5Y 백분위 ${Math.round(ind.percentile)}` : "—"}</span>
    </button>
  );
}

// ── ZHeatmap — 테마×지표 z-score 히트맵 ──
export function ZHeatmap({ themes, onPick }: { themes: MacroTheme[]; onPick: (ind: MacroIndicator) => void }) {
  return (
    <div className="mc-heat">
      {themes.map((t) => (
        <div key={t.key} className="mc-heat-row">
          <div className="mc-heat-lbl">{t.label}<span>{t.indicators.length}</span></div>
          <div className="mc-heat-cells">
            {t.indicators.map((ind) => (
              <button key={ind.id} className="mc-heat-cell" style={{ background: zFill(ind.z_score) }} onClick={() => onPick(ind)} title={`${ind.name}: ${fmtNum(ind.latest)} ${ind.unit} · z ${fmtZ(ind.z_score)}`}>
                <span className="mc-heat-nm">{ind.name}</span>
                <span className="mc-heat-z">{fmtZ(ind.z_score)}</span>
              </button>
            ))}
            {!t.indicators.length && <span className="mc-heat-empty">데이터 없음</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── ValuationBars — 자산군 z-score 막대 ──
export function ValuationBars({ assets }: { assets: Array<{ key: string; label: string; z: number | null }> }) {
  return (
    <div className="mc-valbars">
      {assets.map((a) => (
        <div key={a.key} className="mc-valbar">
          <span className="mc-valbar-lbl">{a.label}</span>
          <ZBar z={a.z} />
          <span className="mc-valbar-z" style={{ color: zScoreColor(a.z) }}>{fmtZ(a.z)}</span>
        </div>
      ))}
    </div>
  );
}

// ── HoldingsDonut — 전략 보유비중 도넛 ──
export function HoldingsDonut({ holdings, size = 116 }: { holdings: TacticalHolding[]; size?: number }) {
  const data = holdings.map((h) => ({ name: h.label, value: h.weight }));
  return (
    <PieChart width={size} height={size}>
      <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={size * 0.29} outerRadius={size * 0.46} paddingAngle={1} stroke="none" isAnimationActive={false}>
        {data.map((_, idx) => <Cell key={idx} fill={DONUT_COLORS[idx % DONUT_COLORS.length]} />)}
      </Pie>
      <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string, name: string) => [`${val}%`, name]} />
    </PieChart>
  );
}
export const donutColor = (idx: number): string => DONUT_COLORS[idx % DONUT_COLORS.length];

// ── SignalBadge ──
export function SignalBadge({ signal }: { signal: string }) {
  return <span className="mc-sig" style={{ color: sigColor(signal), borderColor: sigColor(signal) }}>{signal}</span>;
}

// ── CompositeRow — 추천 랭킹 막대 행 ──
export function CompositeRow({ rank, name, composite, fit, perf, signal, onClick, active }: {
  rank: number; name: string; composite: number; fit: number; perf: number | null; signal: string; onClick?: () => void; active?: boolean;
}) {
  return (
    <button className={`mc-rankrow${active ? " on" : ""}`} onClick={onClick}>
      <span className="mc-rank-no">{rank}</span>
      <span className="mc-rank-nm">{name}</span>
      <div className="mc-rank-bar"><i style={{ width: `${Math.max(2, Math.min(100, composite))}%`, background: sigColor(signal) }} /></div>
      <span className="mc-rank-comp">{composite.toFixed(0)}</span>
      <span className="mc-rank-fit">적합 {fit.toFixed(0)}</span>
      <span className="mc-rank-perf" style={{ color: perf == null ? "var(--t-muted)" : perf >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{perf == null ? "—" : fmtPct(perf)}</span>
    </button>
  );
}

// ── DrillDownModal — 지표 36개월 시계열 + 통계 ──
export function DrillDownModal({ series, loading, onClose }: { series: MacroSeries | null; loading: boolean; onClose: () => void }) {
  const data = series ? series.timestamps.map((t, idx) => ({ t: t.length > 6 ? t.slice(2, 7) : t, v: series.values[idx] })) : [];
  return (
    <div className="mc-modal-bg" onClick={onClose}>
      <div className="mc-modal" onClick={(e) => e.stopPropagation()}>
        <button className="mc-modal-x" onClick={onClose}><X size={16} /></button>
        {loading && <div className="mc-modal-load">시계열 불러오는 중…</div>}
        {!loading && !series && <div className="mc-modal-load">데이터를 불러올 수 없습니다.</div>}
        {!loading && series && (
          <>
            <div className="mc-modal-h">
              <div><b>{series.name}</b><span>{series.indicator} · {series.source}</span></div>
              <div className="mc-modal-latest"><b style={{ color: zScoreColor(series.z_score) }}>{fmtNum(series.latest)}</b><em>{series.unit}</em></div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
                <defs><linearGradient id="mcgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--t-accent)" stopOpacity={0.28} /><stop offset="100%" stopColor="var(--t-accent)" stopOpacity={0.02} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" vertical={false} />
                <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" minTickGap={24} />
                <YAxis tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" domain={["auto", "auto"]} width={46} />
                <Tooltip contentStyle={TIP_STYLE} />
                {series.mean_5y != null && <ReferenceLine y={series.mean_5y} stroke="var(--t-muted)" strokeDasharray="3 3" />}
                <Area type="monotone" dataKey="v" stroke="var(--t-accent)" strokeWidth={1.6} fill="url(#mcgrad)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
            <div className="mc-modal-stats">
              {[["최근값", `${fmtNum(series.latest)} ${series.unit}`], ["5Y 평균", fmtNum(series.mean_5y)], ["5Y 표준편차", fmtNum(series.std_5y)], ["Z-Score", fmtZ(series.z_score)], ["백분위", series.percentile != null ? `${Math.round(series.percentile)}` : "—"], ["전년대비", fmtPct(series.yoy)]].map(([k, v]) => (
                <div key={k} className="mc-modal-stat"><span>{k}</span><b>{v}</b></div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ═══ v2 (CIO 리팩토링) — 확률·분해·게이지·배분 시각화 ═══════════════════════════

// ProbBars — 사분면 확률 분포 (정적 '신뢰도 %' 텍스트 대체, 합=1)
const QUAD_ORDER = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"] as const;
const QUAD_COLOR: Record<string, string> = {
  Goldilocks: "#16a34a", Reflation: "#ea580c", Stagflation: "#dc2626", Disinflation: "#2563eb",
};
export function ProbBars({ probs, compact = false }: { probs: Record<string, number>; compact?: boolean }) {
  if (!probs || !Object.keys(probs).length) return null;
  return (
    <div className={`mc-probbars${compact ? " compact" : ""}`}>
      {QUAD_ORDER.map((q) => {
        const p = (probs[q] ?? 0) * 100;
        return (
          <div key={q} className="mc-pb-row" title={`${q} ${p.toFixed(1)}%`}>
            <span className="mc-pb-k">{compact ? q.slice(0, 4).toUpperCase() : q}</span>
            <div className="mc-pb-track"><i style={{ width: `${Math.max(1.5, p)}%`, background: QUAD_COLOR[q] }} /></div>
            <span className="mc-pb-v">{p.toFixed(0)}%</span>
          </div>
        );
      })}
    </div>
  );
}

// AxisBreakdown — 축 스코어의 지표별 분해(변환 z·모멘텀 z·기여) 테이블.
//   "CPI 레벨 +2.17σ인데 축 -0.28" 모순의 투명화: 축이 실제로 먹는 z(YoY 변환)를 그대로 표시.
export function AxisBreakdown({ title, detail }: { title: string; detail?: { score: number; se: number; components: Array<{ key: string; transform: string; z: number; z_mom: number | null; weight: number; contribution: number }> } }) {
  if (!detail || !detail.components?.length) return null;
  return (
    <div className="mc-axisbd">
      <div className="mc-axisbd-h">{title} <b>{detail.score >= 0 ? "+" : ""}{detail.score.toFixed(2)}</b> <em>±{detail.se.toFixed(2)}</em></div>
      <table className="mc-axisbd-t">
        <thead><tr><th>지표</th><th>변환</th><th>z</th><th>모멘텀z</th><th>가중</th><th>기여</th></tr></thead>
        <tbody>
          {detail.components.map((c) => (
            <tr key={c.key}>
              <td>{c.key}</td>
              <td>{c.transform === "yoy" ? "YoY" : "레벨"}</td>
              <td style={{ color: c.z >= 0 ? "#dc2626" : "#2563eb" }}>{c.z >= 0 ? "+" : ""}{c.z.toFixed(2)}</td>
              <td>{c.z_mom == null ? "—" : `${c.z_mom >= 0 ? "+" : ""}${c.z_mom.toFixed(2)}`}</td>
              <td>{(c.weight * 100).toFixed(0)}%</td>
              <td><b>{c.contribution >= 0 ? "+" : ""}{c.contribution.toFixed(3)}</b></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// CbGauge — 중앙은행 매파/비둘기 게이지 (-1 완화 ~ +1 긴축)
export function CbGauge({ name, bank }: { name: string; bank?: { available: boolean; score?: number; label?: string; hawkish_hits?: number; dovish_hits?: number; terms?: string[]; note?: string } }) {
  if (!bank) return null;
  if (!bank.available) {
    return <div className="mc-cbg"><div className="mc-cbg-h">{name}</div><div className="mc-empty-sm">{bank.note ?? "미수집"}</div></div>;
  }
  const s = bank.score ?? 0;
  const pos = ((s + 1) / 2) * 100;
  return (
    <div className="mc-cbg">
      <div className="mc-cbg-h">{name} <b style={{ color: s > 0.2 ? "#dc2626" : s < -0.2 ? "#2563eb" : "var(--t-muted)" }}>{bank.label}</b></div>
      <div className="mc-cbg-track">
        <i className="mc-cbg-marker" style={{ left: `${pos}%` }} />
      </div>
      <div className="mc-cbg-scale"><span>-1 완화</span><span>0</span><span>+1 긴축</span></div>
      <div className="mc-cbg-meta">매파 용어 {bank.hawkish_hits} · 비둘기 {bank.dovish_hits}{bank.terms?.length ? ` · ${bank.terms.slice(0, 4).join(", ")}` : ""}</div>
    </div>
  );
}

// AllocAttribution — 비중 결정 요인 분해 (base+성장+물가+스트레스 = 최종, 룰 항 정확 분해)
export function AllocAttribution({ rows }: { rows: Array<{ ticker: string; label: string; base: number; growth: number; inflation: number; stress: number; final: number }> }) {
  const TERMS = [["growth", "성장", "#16a34a"], ["inflation", "물가", "#ea580c"], ["stress", "스트레스", "#dc2626"]] as const;
  const maxAbs = Math.max(...rows.flatMap((r) => [Math.abs(r.growth), Math.abs(r.inflation), Math.abs(r.stress)]), 1);
  return (
    <div className="mc-attr">
      {rows.map((r) => (
        <div key={r.ticker} className="mc-attr-row">
          <span className="mc-attr-nm">{r.label}</span>
          <span className="mc-attr-base">기본 {r.base.toFixed(0)}%</span>
          <div className="mc-attr-terms">
            {TERMS.map(([k, lbl, color]) => {
              const v = r[k];
              return (
                <span key={k} className="mc-attr-term" title={`${lbl} ${v >= 0 ? "+" : ""}${v.toFixed(1)}%p`}>
                  <i style={{ width: `${(Math.abs(v) / maxAbs) * 46}px`, background: color, opacity: v >= 0 ? 0.85 : 0.35 }} />
                  <em style={{ color: v >= 0 ? color : "var(--t-muted)" }}>{v >= 0 ? "+" : ""}{v.toFixed(1)}</em>
                </span>
              );
            })}
          </div>
          <b className="mc-attr-final">{r.final.toFixed(1)}%</b>
        </div>
      ))}
      <div className="mc-attr-legend">기본(전천후 중립) + <i style={{ background: "#16a34a" }} />성장 + <i style={{ background: "#ea580c" }} />물가 + <i style={{ background: "#dc2626" }} />스트레스 = 최종 (룰 항 정확 분해)</div>
    </div>
  );
}

// AllocBands — MC 신뢰구간 (p10–p90 밴드 + p50 마커): 단일 점추정 대신 불확실성 제시
export function AllocBands({ bands }: { bands: Array<{ ticker: string; label: string; p10: number; p50: number; p90: number }> }) {
  const hi = Math.max(...bands.map((b) => b.p90), 10);
  return (
    <div className="mc-bands">
      {bands.map((b) => (
        <div key={b.ticker} className="mc-band-row" title={`${b.label} p10 ${b.p10}% · p50 ${b.p50}% · p90 ${b.p90}%`}>
          <span className="mc-band-nm">{b.label}</span>
          <div className="mc-band-track">
            <i className="mc-band-range" style={{ left: `${(b.p10 / hi) * 100}%`, width: `${Math.max(1, ((b.p90 - b.p10) / hi) * 100)}%` }} />
            <i className="mc-band-med" style={{ left: `${(b.p50 / hi) * 100}%` }} />
          </div>
          <span className="mc-band-v">{b.p10.toFixed(0)}~{b.p90.toFixed(0)}%</span>
        </div>
      ))}
      <div className="mc-attr-legend">국면 스코어 불확실성(±se) 하 MC 400회 — 밴드=p10~p90, 마커=중앙값</div>
    </div>
  );
}

// CausalGraphView — 그레인저(예측적) 인과 그래프: 원형 배치 + 방향 엣지(화살표)
export function CausalGraphView({ nodes, edges }: { nodes: Array<{ id: string; label: string }>; edges: Array<{ from: string; to: string; lag: number; p: number }> }) {
  if (!nodes.length) return <div className="mc-empty-sm">그래프 데이터 없음 (시계열 표본 부족)</div>;
  const R = 118, CX = 170, CY = 140;
  const pos: Record<string, { x: number; y: number }> = {};
  nodes.forEach((n, k) => {
    const a = (k / nodes.length) * 2 * Math.PI - Math.PI / 2;
    pos[n.id] = { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) };
  });
  return (
    <svg viewBox="0 0 340 280" className="mc-causal">
      <defs>
        <marker id="mcArrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={5} markerHeight={5} orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#1200ff" opacity={0.65} />
        </marker>
      </defs>
      {edges.map((e, k) => {
        const a = pos[e.from], b = pos[e.to];
        if (!a || !b) return null;
        const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
        const sx = a.x + (dx / len) * 16, sy = a.y + (dy / len) * 16;
        const ex = b.x - (dx / len) * 20, ey = b.y - (dy / len) * 20;
        const w = Math.max(0.6, 2.4 - e.p * 20);   // p 낮을수록 굵게
        return (
          <g key={k}>
            <line x1={sx} y1={sy} x2={ex} y2={ey} stroke="#1200ff" strokeWidth={w} opacity={0.5} markerEnd="url(#mcArrow)">
              <title>{e.from} → {e.to} · lag {e.lag}개월 · p={e.p}</title>
            </line>
          </g>
        );
      })}
      {nodes.map((n) => (
        <g key={n.id}>
          <circle cx={pos[n.id].x} cy={pos[n.id].y} r={13} fill="var(--t-surface, #fafafa)" stroke="var(--t-border, #d5d5d5)" />
          <text x={pos[n.id].x} y={pos[n.id].y + 24} textAnchor="middle" fontSize={7.5} fill="var(--t-muted)">{n.label}</text>
        </g>
      ))}
    </svg>
  );
}
