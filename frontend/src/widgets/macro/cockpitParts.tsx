"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// cockpitParts — 매크로 분석 탭 안 그림 부품 (recharts + SVG)
//   RegimeScatter · CycleClock · ArcGauge · YieldCurveChart · Sparkline · ZBar · IndicatorCard · ZHeatmap ·
//   ValuationBars · HoldingsDonut · SignalBadge · CompositeRow · ProbBars · AxisBreakdown · CbGauge · (배분·인과 그림은 BU5b-2)
// BU5b: 색은 뜻 넷으로 나눴다(`macroKo.ts` 머리 주석) · 영어 열거값은 한국어 · 툴팁(`title=`) 대신 보이는 읽기 줄 ·
//   빈 값 "—" 대신 "몰라요". 그림은 하나도 지우지 않았다(사용자 상시 규칙 — 바꾸되 없애지 않는다).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, ScatterChart, Scatter,
  ReferenceArea, ReferenceLine, ReferenceDot, XAxis, YAxis, CartesianGrid, Tooltip,
  RadialBarChart, RadialBar, PolarAngleAxis, PieChart, Pie, Cell,
} from "recharts";
import type { YieldCurvePoint } from "@/entities/macro/api";
import type { MacroIndicator, MacroTheme, TacticalHolding } from "@/entities/macro/analysisModel";
import { regimeName } from "@/entities/macro/regimeKo";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { CAT_N, IND_KR, catColor, signed, zFill as lvFill } from "./macroKo";

// ── 포맷·색 helpers ── 모르는 값은 "몰라요"(0 이나 "—" 로 그리지 않는다)
export const fmtNum = (v: number | null | undefined, d = 2): string =>
  v == null || !Number.isFinite(v) ? "몰라요" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(d);
export const fmtZ = (z: number | null | undefined): string => (z == null || !Number.isFinite(z) ? "몰라요" : signed(z));
export const fmtPct = (v: number | null | undefined, d = 1): string => (v == null || !Number.isFinite(v) ? "몰라요" : `${signed(v, d)}%`);
export const clamp1 = (v: number): number => Math.max(-1, Math.min(1, v));
/** 수준 색(z) — 주황(평균보다 높음)/청록(낮음) 양쪽 색. 등락 빨강·파랑이 아니다. */
export const zFill = lvFill;
/** 판단(공격/중립/방어)은 색으로 말하지 않는다 — 어느 값이든 같은 중립 잉크. 글자가 판단을 말한다. */
export function sigColor(_sig: string): string { return "var(--tx-ink)"; }
/** 등락색 — 오름 빨강 / 내림 파랑(한국식). 0 은 잉크. */
export const moveColor = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) || v === 0 ? "var(--tx-ink)" : v > 0 ? "var(--tx-up-ink)" : "var(--tx-down-ink)";
export const TIP_STYLE = { background: "var(--tx-surface)", border: "1px solid var(--tx-line)", borderRadius: 12, fontSize: 13, color: "var(--tx-ink)" };
const AX = { fontSize: 12, fill: "var(--tx-sub)" } as const;
const Q_FILL: Record<string, string> = {
  Goldilocks: "var(--mc-q-goldilocks)", Reflation: "var(--mc-q-reflation)",
  Stagflation: "var(--mc-q-stagflation)", Disinflation: "var(--mc-q-disinflation)",
};

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

// ─────────────────────────────────────────────────────────────────────────────
// CycleClock — 경기순환 시계: 네 사분면(국면 색) + 지금 위치 바늘
//   각도 atan2(물가, 성장): 0~90° 리플레이션(성장↑물가↑) · 90~180° 스태그플레이션 · 180~270° 디스인플레이션 · 270~360° 골디락스.
//   (BU5b 고침: 예전 부채꼴은 ±45° 로 돌아가 있어 사분면과 어긋났다 — 성장 0.5·물가 0.87 같은 리플레이션 점이 스태그플레이션 칸에 그려졌다.)
// ─────────────────────────────────────────────────────────────────────────────
export function CycleClock({ g, i, size = 200 }: { g: number; i: number; size?: number }) {
  const cx = size / 2, cy = size / 2, R = size * 0.4;
  const ang = Math.atan2(clamp1(i), clamp1(g)); // 표준 수학각 (x 오른쪽 · y 위)
  const nx = cx + R * Math.cos(ang), ny = cy - R * Math.sin(ang);
  const mag = Math.min(1, Math.hypot(clamp1(g), clamp1(i)));
  const sectors = [
    { a0: 0, a1: 90, q: "Reflation" }, { a0: 90, a1: 180, q: "Stagflation" },
    { a0: 180, a1: 270, q: "Disinflation" }, { a0: 270, a1: 360, q: "Goldilocks" },
  ];
  const arc = (a0: number, a1: number) => {
    const p0 = [cx + R * Math.cos((a0 * Math.PI) / 180), cy - R * Math.sin((a0 * Math.PI) / 180)];
    const p1 = [cx + R * Math.cos((a1 * Math.PI) / 180), cy - R * Math.sin((a1 * Math.PI) / 180)];
    return `M ${cx} ${cy} L ${p0[0].toFixed(1)} ${p0[1].toFixed(1)} A ${R} ${R} 0 0 0 ${p1[0].toFixed(1)} ${p1[1].toFixed(1)} Z`;
  };
  return (
    <div className="mc-clock-wrap">
      <span className="mc-clock-q tl" data-regime="Stagflation"><i style={{ background: Q_FILL.Stagflation }} aria-hidden />{regimeName("Stagflation")}</span>
      <span className="mc-clock-q tr" data-regime="Reflation"><i style={{ background: Q_FILL.Reflation }} aria-hidden />{regimeName("Reflation")}</span>
      <svg width={size} height={size} className="mc-clock" role="img" aria-label={`경기순환 시계: 바늘 방향이 지금 국면, 강도 ${(mag * 100).toFixed(0)}%`}>
        {sectors.map((s) => <path key={s.q} d={arc(s.a0, s.a1)} fill={Q_FILL[s.q]} fillOpacity={0.22} stroke="var(--tx-surface)" strokeWidth={2} data-regime={s.q} />)}
        <circle cx={cx} cy={cy} r={R} fill="none" stroke="var(--tx-line)" strokeWidth={1} />
        <line x1={cx} y1={cy} x2={nx.toFixed(1)} y2={ny.toFixed(1)} stroke="var(--tx-ink)" strokeWidth={2.5} strokeLinecap="round" />
        <circle cx={nx} cy={ny} r={6} fill="var(--tx-ink)" stroke="var(--tx-surface)" strokeWidth={2} />
        <circle cx={cx} cy={cy} r={3.5} fill="var(--tx-ink)" />
      </svg>
      <span className="mc-clock-q bl" data-regime="Disinflation"><i style={{ background: Q_FILL.Disinflation }} aria-hidden />{regimeName("Disinflation")}</span>
      <span className="mc-clock-q br" data-regime="Goldilocks"><i style={{ background: Q_FILL.Goldilocks }} aria-hidden />{regimeName("Goldilocks")}</span>
      <p className="mc-clock-s">바늘이 가리키는 쪽이 지금 국면 · 강도 {(mag * 100).toFixed(0)}%</p>
    </div>
  );
}

// ── ArcGauge — 반원 게이지(스트레스·적합도 점수). ★판정 색 띠 없음★ 값이 달라도 같은 중립색 — 임계값은 서버가 주지 않는다.
//   BU5b: recharts 방사형 막대 대신 머리의 스트레스 반원(`RegimeVisual`)과 같은 SVG 반원 — 숫자가 호 안쪽에 겹치던 것을 고쳤다. ──
const AG_R = 70, AG_L = Math.PI * AG_R;
export function ArcGauge({ value, max = 100, label, sub }: { value: number | null | undefined; max?: number; color?: string; label: string; sub?: string; height?: number }) {
  const known = value != null && Number.isFinite(value);
  const frac = known ? Math.max(0, Math.min(1, (value as number) / max)) : 0;
  const arc = `M 20 90 A ${AG_R} ${AG_R} 0 0 1 160 90`;
  return (
    <div className="mc-gauge" role="img" aria-label={known ? `${Math.round(value as number)}${label}${sub ? `, ${sub}` : ""}` : "값을 받지 못했어요"}>
      <div className="mc-gauge-dial">
        <svg viewBox="0 0 180 100" width="200" height="111" aria-hidden>
          <path d={arc} className="mc-gauge-track" fill="none" strokeWidth="14" strokeLinecap="round" />
          {known && frac > 0 && <path d={arc} className="mc-gauge-fill" fill="none" strokeWidth="14" strokeLinecap="round" strokeDasharray={`${frac * AG_L} ${AG_L}`} />}
        </svg>
        <div className="mc-gauge-c">{known ? <><b>{Math.round(value as number)}</b><span>{label}</span></> : <span>몰라요</span>}</div>
      </div>
      <div className="mc-gauge-ends" aria-hidden><span>0 · 잔잔해요</span><span>{max} · 불안해요</span></div>
      {sub && <div className="mc-gauge-sub">{sub}</div>}
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

// ── Sparkline — 작은 선(지표 카드). "auto" = 처음보다 오르면 빨강 · 내리면 파랑(등락색, 한국식). ──
export function Sparkline({ values, w = 200, h = 30, color = "var(--tx-blue)" }: { values: number[]; w?: number; h?: number; color?: string }) {
  const vals = (values || []).filter((v) => Number.isFinite(v));
  if (vals.length < 2) return <svg width={w} height={h} className="mc-spark" aria-hidden />;
  const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
  const step = w / (vals.length - 1);
  const pts = vals.map((v, idx) => `${(idx * step).toFixed(1)},${(h - ((v - min) / range) * (h - 4) - 2).toFixed(1)}`).join(" ");
  const c = color === "auto" ? (vals[vals.length - 1] >= vals[0] ? "var(--tx-up)" : "var(--tx-down)") : color;
  return <svg width={w} height={h} className="mc-spark" preserveAspectRatio="none" viewBox={`0 0 ${w} ${h}`} aria-hidden><polyline points={pts} fill="none" stroke={c} strokeWidth={1.6} /></svg>;
}

// ── ZBar — z 막대(가운데 0, −3..+3). 수준 색. 모르면 채우지 않는다(0 으로 그리지 않는다). ──
export function ZBar({ z }: { z: number | null | undefined }) {
  const known = z != null && Number.isFinite(z);
  const v = known ? Math.max(-3, Math.min(3, z as number)) : 0;
  const w = (Math.abs(v) / 3) * 50;
  return (
    <div className="mc-zbar" aria-hidden>
      <div className="mc-zbar-mid" />
      {known && <div className="mc-zbar-fill" style={{ width: `${w}%`, background: zFill(z), ...(v >= 0 ? { left: "50%" } : { right: "50%" }) }} />}
    </div>
  );
}

// ── IndicatorCard — 지표 카드(누르면 36개월 흐름) ──
export function IndicatorCard({ ind, onClick }: { ind: MacroIndicator; onClick?: () => void }) {
  const d = ind.delta;
  const hasD = d != null && Number.isFinite(d);
  return (
    <button type="button" className="mc-ind" onClick={onClick}>
      <div className="mc-ind-h"><span className="mc-ind-nm">{ind.name}</span><span className="mc-ind-z"><i style={{ background: zFill(ind.z_score) }} aria-hidden />z {fmtZ(ind.z_score)}</span></div>
      <div className="mc-ind-v">
        <b>{fmtNum(ind.latest)}</b><em>{ind.unit}</em>
        {hasD && <span className="mc-ind-d" style={{ color: moveColor(d) }}>{(d as number) >= 0 ? "▲" : "▼"} {fmtNum(Math.abs(d as number))}</span>}
      </div>
      {/* 선은 중립색 — 오름/내림 색은 ▲▼(지난번 대비) 하나만 쓴다(24개월 처음↔끝 비교로 칠하면 ▲▼ 와 반대 색이 나올 수 있었다) */}
      <Sparkline values={ind.spark} w={210} h={28} color="var(--mc-neutral)" />
      <div className="mc-ind-pct" aria-hidden><i style={{ width: `${Math.max(2, Math.min(100, ind.percentile ?? 0))}%`, opacity: ind.percentile == null ? 0 : 1 }} /></div>
      <span className="mc-ind-pctlbl">{ind.percentile != null ? `지난 5년 중 위치 ${Math.round(ind.percentile)}%` : "지난 5년 중 위치 몰라요"}</span>
    </button>
  );
}

// ── ZHeatmap — 묶음 × 지표 z 지도. 칸에 올리거나 초점을 두면 아래 읽기 줄이 그 칸을 말한다(툴팁 아님 — 키보드로도 읽힌다). ──
export function ZHeatmap({ themes, onPick }: { themes: MacroTheme[]; onPick: (ind: MacroIndicator) => void }) {
  const [cur, setCur] = useState<MacroIndicator | null>(null);
  return (
    <div className="mc-heat">
      {themes.map((t) => (
        <div key={t.key} className="mc-heat-row">
          <div className="mc-heat-lbl">{t.label}<span>{t.indicators.length}개</span></div>
          <div className="mc-heat-cells">
            {t.indicators.map((ind) => (
              <button key={ind.id} type="button" className="mc-heat-cell" style={{ background: zFill(ind.z_score) }}
                      onClick={() => onPick(ind)} onFocus={() => setCur(ind)} onMouseEnter={() => setCur(ind)}
                      aria-label={`${ind.name}, z ${fmtZ(ind.z_score)}, 눌러서 36개월 흐름 보기`}>
                <span className="mc-heat-nm">{ind.name}</span>
                <span className="mc-heat-z">{fmtZ(ind.z_score)}</span>
              </button>
            ))}
            {!t.indicators.length && <span className="mc-heat-empty">이 묶음에는 지표가 없어요</span>}
          </div>
        </div>
      ))}
      <p className="mc-readout" aria-live="polite">
        {cur
          ? <><b>{cur.name}</b> {fmtNum(cur.latest)} {cur.unit} · z {fmtZ(cur.z_score)}{cur.percentile != null && ` · 지난 5년 중 위치 ${Math.round(cur.percentile)}%`}</>
          : "칸에 마우스를 올리거나 Tab 으로 옮기면 여기에 값이 나와요"}
      </p>
    </div>
  );
}

// ── ValuationBars — 자산군 z 막대(수준 색) ──
export function ValuationBars({ assets }: { assets: Array<{ key: string; label: string; z: number | null }> }) {
  return (
    <div className="mc-valbars">
      {assets.map((a) => (
        <div key={a.key} className="mc-valbar">
          <span className="mc-valbar-lbl">{a.label}</span>
          <ZBar z={a.z} />
          <span className="mc-valbar-z">{fmtZ(a.z)}</span>
        </div>
      ))}
    </div>
  );
}

/** 보유 목록을 범주 색 수(7) 안으로 — 넘치면 작은 것부터 "기타" 하나로 합친다(지우지 않는다 · 합은 그대로). */
export function foldHoldings<T extends { weight: number }>(hs: T[], label: (h: T) => string): Array<{ name: string; value: number; color: string }> {
  const rows = hs.map((h) => ({ name: label(h), value: h.weight }));
  if (rows.length <= CAT_N) return rows.map((r, i) => ({ ...r, color: catColor(i) }));
  const head = rows.slice(0, CAT_N - 1).map((r, i) => ({ ...r, color: catColor(i) }));
  const rest = rows.slice(CAT_N - 1).reduce((a, r) => a + r.value, 0);
  return [...head, { name: `기타 ${rows.length - (CAT_N - 1)}개`, value: Math.round(rest * 10) / 10, color: "var(--mc-c-etc)" }];
}

// ── HoldingsDonut — 전략 보유 비중 도넛(범주 색 · 8 개 넘으면 기타로 접음) ──
export function HoldingsDonut({ holdings, size = 116 }: { holdings: TacticalHolding[]; size?: number }) {
  const anim = useChartAnimation();
  const data = foldHoldings(holdings, (h) => h.label);
  return (
    <PieChart width={size} height={size}>
      <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={size * 0.29} outerRadius={size * 0.46} paddingAngle={1.5} stroke="var(--tx-surface)" isAnimationActive={anim}>
        {data.map((d, idx) => <Cell key={idx} fill={d.color} />)}
      </Pie>
      <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string, name: string) => [`${val}%`, name]} />
    </PieChart>
  );
}
/** 보유 목록 i 번째 칸의 색 — 도넛과 같은 순서. 목록이 7 개를 넘으면 7 번째부터는 도넛의 "기타" 회색과 같다(`total` 을 넘길 때). */
export const donutColor = (idx: number, total = 0): string =>
  total > CAT_N && idx >= CAT_N - 1 ? "var(--mc-c-etc)" : catColor(idx);

// ── SignalBadge — 서버 신호 글자(공격/중립/방어). 색으로 판단하지 않는다(중립 알약). ──
export function SignalBadge({ signal }: { signal: string }) {
  return <span className="mc-sig">{signal}</span>;
}

// ── CompositeRow — 추천 순위 막대 줄. 막대 = 종합 점수(중립) · 12개월 성과 = 등락색 + 부호. ──
export function CompositeRow({ rank, name, composite, fit, perf, signal: _signal, onClick, active }: {
  rank: number; name: string; composite: number; fit: number; perf: number | null; signal: string; onClick?: () => void; active?: boolean;
}) {
  return (
    <button type="button" className={`mc-rankrow${active ? " on" : ""}`} onClick={onClick}>
      <span className="mc-rank-no">{rank}</span>
      <span className="mc-rank-nm">{name}</span>
      <div className="mc-rank-bar"><i style={{ width: `${Math.max(2, Math.min(100, composite))}%`, background: "var(--mc-neutral)" }} /></div>
      <span className="mc-rank-comp">{composite.toFixed(0)}</span>
      <span className="mc-rank-fit">적합 {fit.toFixed(0)}</span>
      <span className="mc-rank-perf" style={{ color: moveColor(perf) }}>{fmtPct(perf)}</span>
    </button>
  );
}

// ═══ 확률·분해·게이지 ═══════════════════════════════════════════════════════════

// ProbBars — 네 국면 확률(합 100%). 막대 = 국면 색. 이름은 한국어.
const QUAD_ORDER = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"] as const;
export function ProbBars({ probs, compact = false }: { probs: Record<string, number>; compact?: boolean }) {
  if (!probs || !Object.keys(probs).length) return null;
  return (
    <div className={`mc-probbars${compact ? " compact" : ""}`}>
      {QUAD_ORDER.map((q) => {
        const raw = probs[q];
        const known = typeof raw === "number" && Number.isFinite(raw);
        const p = known ? raw * 100 : 0;
        return (
          <div key={q} className="mc-pb-row" data-regime={q}>
            <span className="mc-pb-k">{regimeName(q)}</span>
            <div className="mc-pb-track" aria-hidden><i style={{ width: `${known ? Math.max(1.5, p) : 0}%`, background: Q_FILL[q] }} /></div>
            <span className="mc-pb-v">{known ? `${p.toFixed(0)}%` : "몰라요"}</span>
          </div>
        );
      })}
    </div>
  );
}

// AxisBreakdown — 축 점수의 지표별 분해(바꾼 z·모멘텀 z·기여). 축이 실제로 먹는 z 를 그대로 보인다.
export function AxisBreakdown({ title, detail }: { title: string; detail?: { score: number; se: number; components: Array<{ key: string; transform: string; z: number; z_mom: number | null; weight: number; contribution: number }> } }) {
  if (!detail || !detail.components?.length) return null;
  return (
    <div className="mc-axisbd">
      <div className="mc-axisbd-h">{title} <b>{signed(detail.score)}</b> <em>±{detail.se.toFixed(2)}</em></div>
      <div className="mc-tablewrap">
        <table className="mc-axisbd-t">
          <thead><tr><th>지표</th><th>바꾼 방식</th><th>z</th><th>3개월 모멘텀 z</th><th>가중</th><th>기여</th></tr></thead>
          <tbody>
            {detail.components.map((c) => (
              <tr key={c.key}>
                <td>{IND_KR[c.key] ?? c.key}</td>
                <td>{c.transform === "yoy" ? "전년 대비" : "수준"}</td>
                <td><span className="mc-zcell" style={{ background: zFill(c.z) }}>{signed(c.z)}</span></td>
                <td>{c.z_mom == null ? "몰라요" : signed(c.z_mom)}</td>
                <td>{(c.weight * 100).toFixed(0)}%</td>
                <td><b>{signed(c.contribution, 3)}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// CbGauge — 중앙은행 말투 게이지(−1 완화 ~ +1 긴축). 띠는 수준 색(청록 ↔ 주황) · 표식은 잉크.
export function CbGauge({ name, bank }: { name: string; bank?: { available: boolean; score?: number; label?: string; hawkish_hits?: number; dovish_hits?: number; terms?: string[]; note?: string } }) {
  if (!bank) return null;
  if (!bank.available) {
    return (
      <div className="mc-cbg">
        <div className="mc-cbg-h">{name}</div>
        <p className="mc-cbg-none">점수를 내지 못했어요. <span data-server>{bank.note ?? "정책문을 받지 못했어요"}</span></p>
      </div>
    );
  }
  const s = bank.score ?? 0;
  const pos = ((Math.max(-1, Math.min(1, s)) + 1) / 2) * 100;
  return (
    <div className="mc-cbg">
      <div className="mc-cbg-h">{name} <b data-server>{bank.label}</b></div>
      <div className="mc-cbg-track" role="img" aria-label={`${name} 말투 점수 ${signed(s)}`}>
        <i className="mc-cbg-marker" style={{ left: `${pos}%` }} />
      </div>
      <div className="mc-cbg-scale"><span>−1 완화</span><span>0</span><span>+1 긴축</span></div>
      <div className="mc-cbg-meta">긴축 쪽 낱말 {bank.hawkish_hits}번 · 완화 쪽 {bank.dovish_hits}번{bank.terms?.length ? <> · <span data-server>{bank.terms.slice(0, 4).join(", ")}</span></> : null}</div>
    </div>
  );
}

// AllocAttribution — 비중 결정 요인 분해 (base+성장+물가+스트레스 = 최종, 룰 항 정확 분해)
export function AllocAttribution({ rows }: { rows: Array<{ ticker: string; label: string; base: number; growth: number; inflation: number; stress: number; final: number }> }) {
  const TERMS = [["growth", "성장", "var(--hx-t-16a34a)"], ["inflation", "물가", "var(--hx-t-ea580c)"], ["stress", "스트레스", "var(--hx-t-dc2626)"]] as const;
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
      <div className="mc-attr-legend">기본(전천후 중립) + <i style={{ background: "var(--hx-b-16a34a)" }} />성장 + <i style={{ background: "var(--hx-b-ea580c)" }} />물가 + <i style={{ background: "var(--hx-b-dc2626)" }} />스트레스 = 최종 (룰 항 정확 분해)</div>
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
          <path d="M0,0 L8,4 L0,8 z" fill="var(--hx-t-1200ff)" opacity={0.65} />
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
            <line x1={sx} y1={sy} x2={ex} y2={ey} stroke="var(--hx-t-1200ff)" strokeWidth={w} opacity={0.5} markerEnd="url(#mcArrow)">
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
