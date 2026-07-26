"use client";
// visualParts — 밸리AI 거시경제 분석의 장점 흡수 컴포넌트 (v3)
//   CycleStripGrid(사이클 히트 스트립) · AxisStackChart(하위요인 시계열 분해) ·
//   AssetStripGrid(자산군 가격 위치 백분위) · KrUsCompareTable(국가 비교) · buildBriefing.
import React from "react";
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ReferenceLine,
} from "recharts";
import { zFill } from "./cockpitParts";
import type { CycleStrips, AxisHistory, AssetStrips, KrUsCompare } from "@/shared/api/screenerApi";
import type { RegimeState } from "@/entities/macro/api";

const TIP = { background: "#fff", border: "1px solid var(--t-border)", borderRadius: 2, fontSize: 11 } as const;

// 지표 키 → 짧은 한글 (브리핑·스택 범례 공용)
export const IND_KR: Record<string, string> = {
  KR_LEADING_CYCLE: "경기선행", KR_IP: "산업생산", KOSPI: "KOSPI", KR_CPI: "CPI",
  KR_10Y: "국고10Y", USD_KRW: "환율", CPIAUCSL: "CPI", INDPRO: "산업생산",
  PAYEMS: "고용", UNRATE: "실업률", GDPC1: "GDP", T10YIE: "기대인플레",
  DGS10: "미10Y", VIXCLS: "VIX", BAMLH0A0HYM2: "HY스프레드",
};

// ── 사이클 히트 스트립: 지표 × 월 색 띠 (밸리 '사이클 분석') ──
export function CycleStripGrid({ data }: { data: CycleStrips }) {
  if (!data.indicators.length) return <div className="mc-empty-sm">스트립 데이터 없음</div>;
  const months = data.months;
  return (
    <div className="mv-strips">
      {data.indicators.map((row) => (
        <div key={row.key} className="mv-strip-row">
          <span className="mv-strip-lbl">{row.label}</span>
          <div className="mv-strip-cells">
            {row.cells.map((z, i) => (
              <i key={i} style={{ background: zFill(z) }}
                title={`${months[i]} · ${row.label}: ${z == null ? "—" : (z >= 0 ? "+" : "") + z.toFixed(2) + "σ"}`} />
            ))}
          </div>
          <b className="mv-strip-now" style={{ color: (row.cells.at(-1) ?? 0) >= 0 ? "#dc2626" : "#2563eb" }}>
            {row.cells.at(-1) == null ? "—" : `${(row.cells.at(-1) as number) >= 0 ? "+" : ""}${(row.cells.at(-1) as number).toFixed(1)}σ`}
          </b>
        </div>
      ))}
      <div className="mv-strip-axis">
        <span>{months[0]}</span><span>{months[Math.floor(months.length / 2)]}</span><span>{months.at(-1)}</span>
      </div>
    </div>
  );
}

// ── 하위요인 시계열 분해: 축 스코어 = 지표 기여 스택 (밸리 '하위요인 분석') ──
export function AxisStackChart({ hist, axis }: { hist: AxisHistory; axis: "growth" | "inflation" }) {
  const partsKey = axis === "growth" ? "growth_parts" : "inflation_parts";
  const keys = Array.from(new Set(hist.points.flatMap((p) => Object.keys(p[partsKey] ?? {}))));
  const COLORS = ["#1200ff", "#16a34a", "#ea580c", "#0891b2", "#a16207", "#7c3aed"];
  const data = hist.points.map((p) => ({
    t: p.t, score: p[axis],
    ...Object.fromEntries(keys.map((k) => [k, p[partsKey]?.[k] ?? 0])),
  }));
  return (
    <ResponsiveContainer width="100%" height={210}>
      <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -14 }} stackOffset="sign">
        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" interval={Math.floor(data.length / 6)} />
        <YAxis tick={{ fontSize: 9, fill: "var(--t-muted)" }} stroke="var(--t-border)" />
        <ReferenceLine y={0} stroke="var(--t-border)" />
        <Tooltip contentStyle={TIP} formatter={(v: number | string, name: string) => [`${Number(v).toFixed(3)}`, IND_KR[name] ?? name]} />
        {keys.map((k, i) => (
          <Bar key={k} dataKey={k} stackId="s" fill={COLORS[i % COLORS.length]} fillOpacity={0.75} isAnimationActive={false} />
        ))}
        <Line dataKey="score" stroke="#111" strokeWidth={1.6} dot={false} isAnimationActive={false} name={axis === "growth" ? "성장 축" : "물가 축"} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── 자산군 가격 위치 백분위 스트립 (밸리 '자산군 밸류에이션'의 시세 기반 정직 버전) ──
function pctFill(p: number | null): string {
  if (p == null) return "rgba(113,113,122,0.08)";
  const t = (p - 50) / 50;   // -1(저점권)..+1(고점권)
  const a = 0.12 + 0.62 * Math.abs(t);
  return t >= 0 ? `rgba(220,38,38,${a.toFixed(3)})` : `rgba(22,163,74,${a.toFixed(3)})`;
}
export function AssetStripGrid({ data }: { data: AssetStrips }) {
  if (!data.assets.length) return <div className="mc-empty-sm">자산 시세 미적재 (ETF 시세 적재 후 표시)</div>;
  return (
    <div className="mv-strips">
      {data.assets.map((a) => (
        <div key={a.ticker} className="mv-strip-row">
          <span className="mv-strip-lbl">{a.label} <em>{a.ticker}</em></span>
          <div className="mv-strip-cells">
            {a.cells.map((p, i) => (
              <i key={i} style={{ background: pctFill(p) }} title={`${a.label}: ${p == null ? "—" : p + "백분위"}`} />
            ))}
          </div>
          <b className="mv-strip-now">{a.now == null ? "—" : `${a.now}%`}</b>
        </div>
      ))}
      <div className="mv-strip-legend"><i style={{ background: "rgba(22,163,74,.6)" }} />저점권 · <i style={{ background: "rgba(220,38,38,.6)" }} />고점권 (가격 위치 백분위 · 5년)</div>
    </div>
  );
}

// ── KR vs US 비교 테이블 (밸리 '국가경제 분석'의 2국 정직 버전) ──
export function KrUsCompareTable({ data }: { data: KrUsCompare }) {
  if (!data.rows.length) return <div className="mc-empty-sm">비교 데이터 없음</div>;
  const cell = (z: number | null) => (
    <td style={{ background: zFill(z) }}>{z == null ? "—" : `${z >= 0 ? "+" : ""}${z.toFixed(2)}`}</td>
  );
  return (
    <table className="mv-cmp">
      <thead><tr><th>지표 (동일 변환 z)</th><th>🇰🇷 KR</th><th>🇺🇸 US</th><th>KR−US</th></tr></thead>
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.label}>
            <td>{r.label}</td>
            {cell(r.kr)}{cell(r.us)}
            <td style={{ fontFamily: "var(--t-mono, monospace)" }}>{r.gap == null ? "—" : `${r.gap >= 0 ? "+" : ""}${r.gap.toFixed(2)}`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ═══ 상단 3분할 카드 (Gemini UI 개편 1순위 — 도넛 중심 국면 요약) ═══════════════

const QUAD_TONE2: Record<string, string> = {
  Goldilocks: "#16a34a", Reflation: "#ea580c", Stagflation: "#dc2626", Disinflation: "#2563eb",
};
const QUAD_SHORT: Record<string, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션", Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

// 도넛 링 (SVG) — 중앙 타이포 공간 활용: P% 볼드 + 국면명
function DonutRing({ pct, color, big, small, size = 108 }: {
  pct: number; color: string; big: string; small: string; size?: number;
}) {
  const r = 42, C = 2 * Math.PI * r;
  const filled = Math.max(0.02, Math.min(1, pct)) * C;
  return (
    <svg width={size} height={size} viewBox="0 0 108 108" className="mv-donut" role="img"
      aria-label={`${small} ${big}`}>
      <circle cx={54} cy={54} r={r} fill="none" stroke="var(--t-border, #ececf0)" strokeWidth={11} />
      <circle cx={54} cy={54} r={r} fill="none" stroke={color} strokeWidth={11}
        strokeDasharray={`${filled} ${C - filled}`} strokeLinecap="round"
        transform="rotate(-90 54 54)" />
      <text x={54} y={52} textAnchor="middle" className="mv-donut-big">{big}</text>
      <text x={54} y={68} textAnchor="middle" className="mv-donut-small">{small}</text>
    </svg>
  );
}

// ▲/▼ 필 배지 — 서브 지표 톤다운 (성장/물가 축)
function AxisPill({ label, v, upGood }: { label: string; v: number; upGood: boolean }) {
  const up = v >= 0;
  const good = up === upGood;
  const fg = good ? "#0e7c4a" : "#b0325a";
  const bg = good ? "rgba(22,163,74,.10)" : "rgba(220,38,38,.09)";
  return (
    <span className="mv-pill" style={{ color: fg, background: bg }}>
      {label} {up ? "▲" : "▼"} {up ? "+" : ""}{v.toFixed(2)}
    </span>
  );
}

// KR/US 국면 카드 — 도넛(1위 확률) + 국면명 + 서브 필 + 상위 2개 확률
export function RegimeDonutCard({ label, state }: { label: string; state: RegimeState }) {
  const probs = state.regime_probs ?? {};
  const top = state.regime && probs[state.regime] != null ? state.regime
    : (Object.entries(probs).sort((a, b) => b[1] - a[1])[0]?.[0] ?? state.regime);
  const p = probs[top] ?? state.confidence ?? 0;
  const color = QUAD_TONE2[top] ?? "#1200ff";
  const others = Object.entries(probs).filter(([k]) => k !== top).sort((a, b) => b[1] - a[1]).slice(0, 2);
  return (
    <div className="mv-rcard" style={{ borderTopColor: color }}>
      <DonutRing pct={p} color={color} big={`${Math.round(p * 100)}%`} small={top} />
      <div className="mv-rcard-r">
        <span className="mv-rcard-lbl">{label}</span>
        <b className="mv-rcard-quad" style={{ color }}>{QUAD_SHORT[top] ?? top}</b>
        <div className="mv-rcard-pills">
          <AxisPill label="성장" v={state.growth_axis} upGood />
          <AxisPill label="물가" v={state.inflation_axis} upGood={false} />
        </div>
        <div className="mv-rcard-others">
          {others.map(([k, v]) => (
            <span key={k}><i style={{ background: QUAD_TONE2[k] }} />{k.slice(0, 4).toUpperCase()} {(v * 100).toFixed(0)}%</span>
          ))}
        </div>
      </div>
    </div>
  );
}

// Stress·모드 카드 — 도넛(0-100) + 모드 뱃지 + 역전 경고
export function StressModeCard({ state, realData, asOf }: { state: RegimeState; realData: boolean; asOf: string }) {
  const s = state.stress_score;
  const color = s >= 70 ? "#dc2626" : s >= 50 ? "#d97706" : "#16a34a";
  const modeBg = state.recommended_mode === "DEFENSIVE" ? "rgba(220,38,38,.12)"
    : state.recommended_mode === "CAUTIOUS" ? "rgba(217,119,6,.12)" : "rgba(22,163,74,.10)";
  const modeFg = state.recommended_mode === "DEFENSIVE" ? "#b91c1c"
    : state.recommended_mode === "CAUTIOUS" ? "#b45309" : "#0e7c4a";
  return (
    <div className="mv-rcard" style={{ borderTopColor: color }}>
      <DonutRing pct={s / 100} color={color} big={s.toFixed(0)} small="STRESS" />
      <div className="mv-rcard-r">
        <span className="mv-rcard-lbl">시장 스트레스 · 모드</span>
        <b className="mv-rcard-quad"><span className="mv-pill" style={{ color: modeFg, background: modeBg }}>{state.recommended_mode}</span></b>
        <div className="mv-rcard-pills">
          {state.yield_inversion && (
            <span className="mv-pill" style={{ color: "#b0325a", background: "rgba(220,38,38,.09)" }}>
              수익률곡선 역전 {state.inversion_severity != null ? `${state.inversion_severity.toFixed(0)}bp` : ""}
            </span>
          )}
        </div>
        <div className="mv-rcard-others">
          <span className={realData ? "mv-src-real" : "mv-src-mock"}>{realData ? "실데이터" : "MOCK"}</span>
          <span>{asOf}</span>
        </div>
      </div>
    </div>
  );
}

// ── 한줄 브리핑 (밸리의 '차례로 짚어보기' 스토리텔링 — 규칙 기반 자동 문장) ──
export function buildBriefing(st: RegimeState): string {
  const probs = st.regime_probs ?? {};
  const p = Math.round((probs[st.regime] ?? st.confidence ?? 0) * 100);
  const topOf = (d?: { components: Array<{ key: string; contribution: number }> }) => {
    if (!d?.components?.length) return null;
    const c = [...d.components].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))[0];
    return IND_KR[c.key] ?? c.key;
  };
  const gTop = topOf(st.axis_detail?.growth);
  const iTop = topOf(st.axis_detail?.inflation);
  const g = st.growth_axis, i = st.inflation_axis;
  return `지금 국면은 ${st.regime} (P=${p}%) — 성장 ${g >= 0 ? "+" : ""}${g.toFixed(2)}${gTop ? ` (${gTop} 주도)` : ""}, ` +
    `물가 ${i >= 0 ? "+" : ""}${i.toFixed(2)}${iTop ? ` (${iTop} 주도)` : ""} · Stress ${st.stress_score.toFixed(0)} ${st.recommended_mode}`;
}
