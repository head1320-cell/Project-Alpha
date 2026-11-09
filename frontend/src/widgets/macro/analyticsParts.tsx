"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// analyticsParts — 상관 · 타이밍 · 국면 궤적 그림 (recharts + SVG)
//   CorrMatrix · RollingCorrChart · AvgCorrChart · ComponentBars · TimingHistory · TrendTable · RegimeTrajectory.
// BU5b-2: 상관 = 수준 양쪽 색(주황 같이 움직임 / 청록 반대로) · 상관 선 = 범주색 · 점수(신호·종합) = 중립(판단은 글자) ·
//   가격 방향(이동평균 대비·12개월 모멘텀·추세) = 등락색 + 부호 · 툴팁 대신 읽기 줄 · 그림은 하나도 지우지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import type { MacroCorrelations, TimingComponent, TrendRow } from "@/entities/macro/analysisModel";
import { moveColor } from "./cockpitParts";
import { signed } from "./macroKo";
import { chartModule, lazyChart } from "@/shared/ui/lazyChart";

// 이 파일의 차트(RollingCorrChart, AvgCorrChart, TimingHistory, RegimeTrajectory) 코드 — 화면이 뜬 뒤에 받는다(recharts 를 첫 화면 JS 에서 뺌 · lazyChart).
// MacroCockpit 이 붙자마자 불러 데이터와 같이 오게 한다. 이름·prop 은 그대로라 소비자는 바뀌지 않는다.
export const loadAnalyticsCharts = chartModule(() => import("./analyticsParts.charts"));

export const AX = { fontSize: 11, fill: "var(--tx-sub)" } as const;
/** 상관(−1..+1) → 칸 바탕. |c| 0.2·0.4·0.7 경계로 쪽마다 3 단 — 그리기 위한 구간이지 판단이 아니다(값은 늘 글자로). */
export function corrFill(c: number | null | undefined): string {
  if (c == null || !Number.isFinite(c)) return "var(--mc-lv-none)";
  const a = Math.abs(c);
  if (a < 0.2) return "var(--mc-lv-mid)";
  const k = a < 0.4 ? 1 : a < 0.7 ? 2 : 3;
  return `var(--mc-lv-${c > 0 ? "pos" : "neg"}-${k})`;
}
/** 범례 글자를 선 색이 아니라 잉크로 — 노랑·분홍 선 색 글자는 AA 를 떨어뜨린다(BU4 에서 배운 것). */
export const inkLegend = (v: string) => <span style={{ color: "var(--tx-ink)" }}>{v}</span>;

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

export const RollingCorrChart = lazyChart(loadAnalyticsCharts, (m) => m.RollingCorrChart, { height: 260, label: "이동 상관" });   // 본문은 analyticsParts.charts.tsx(화면이 뜬 뒤에 받는다)

export const AvgCorrChart = lazyChart(loadAnalyticsCharts, (m) => m.AvgCorrChart, { height: 200, label: "평균 상관" });   // 본문은 analyticsParts.charts.tsx(화면이 뜬 뒤에 받는다)

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

export const TimingHistory = lazyChart(loadAnalyticsCharts, (m) => m.TimingHistory, { height: 210, label: "타이밍 이력" });   // 본문은 analyticsParts.charts.tsx(화면이 뜬 뒤에 받는다)

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

export const RegimeTrajectory = lazyChart(loadAnalyticsCharts, (m) => m.RegimeTrajectory, { height: 320, label: "국면 궤적" });   // 본문은 analyticsParts.charts.tsx(화면이 뜬 뒤에 받는다)
