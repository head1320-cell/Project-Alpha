"use client";
// visualParts — 밸리AI 거시경제 분석의 장점 흡수 컴포넌트 (v3)
//   CycleStripGrid(사이클 히트 스트립) · AxisStackChart(하위요인 시계열 분해) ·
//   AssetStripGrid(자산군 가격 위치 백분위) · KrUsCompareTable(국가 비교).
//   (BU5a: 머리의 도넛 카드·브리핑 문장은 답 한 문장으로 바뀌어 지웠다 — 같은 숫자를 세 번 말하던 자리.)
import React from "react";
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ReferenceLine,
} from "recharts";
import { zFill } from "./cockpitParts";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";
import { useChartAnimation } from "@/shared/ui/chartStyle";

const TIP = { background: "var(--hx-b-ffffff)", border: "1px solid var(--t-border)", borderRadius: 2, fontSize: 11 } as const;

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
          <b className="mv-strip-now" style={{ color: (row.cells.at(-1) ?? 0) >= 0 ? "var(--hx-t-dc2626)" : "var(--hx-t-2563eb)" }}>
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
  const anim = useChartAnimation();
  const partsKey = axis === "growth" ? "growth_parts" : "inflation_parts";
  const keys = Array.from(new Set(hist.points.flatMap((p) => Object.keys(p[partsKey] ?? {}))));
  const COLORS = ["var(--hx-t-1200ff)", "var(--hx-t-16a34a)", "var(--hx-t-ea580c)", "var(--hx-t-0891b2)", "var(--hx-t-a16207)", "var(--hx-t-7c3aed)"];
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
          <Bar key={k} dataKey={k} stackId="s" fill={COLORS[i % COLORS.length]} fillOpacity={0.75} isAnimationActive={anim} />
        ))}
        <Line dataKey="score" stroke="var(--hx-t-111111)" strokeWidth={1.6} dot={false} isAnimationActive={anim} name={axis === "growth" ? "성장 축" : "물가 축"} />
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
