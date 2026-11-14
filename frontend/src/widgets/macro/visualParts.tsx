"use client";
// visualParts — 사이클 띠 · 축 하위요인 쌓기 · 자산군 가격 위치 띠 · 한국/미국 비교 표
//   (BU5a: 머리의 도넛 카드·브리핑 문장은 답 한 문장으로 바뀌어 지웠다. BU5a+ 에서 도넛은 `RegimeVisual` 로 다시 지었다.)
// BU5b: 띠·표 칸은 수준 색(주황/청록) · 툴팁 대신 보이는 읽기 줄(칸에 올리거나 줄에 초점) · 쌓기 차트에 범례를 붙였다
//   (예전엔 여섯 색이 무엇인지 화면 어디에도 없었다) · 국기 이모지·고정폭 걷음. 그림은 하나도 지우지 않았다.
import React, { useState } from "react";
import type { AssetStrips, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";
import { IND_KR, pctFill, signed, ym, zFill } from "./macroKo";
import { chartModule, lazyChart } from "@/shared/ui/lazyChart";

// 이 파일의 차트(AxisStackChart) 코드 — 화면이 뜬 뒤에 받는다(recharts 를 첫 화면 JS 에서 뺌 · lazyChart).
// MacroCockpit 이 붙자마자 불러 데이터와 같이 오게 한다. 이름·prop 은 그대로라 소비자는 바뀌지 않는다.
export const loadVisualCharts = chartModule(() => import("./visualParts.charts"));

export { IND_KR } from "./macroKo";

/** 띠 줄 이름 — 지표 키를 한국어로(바꾼 방식이 전년 대비면 덧붙인다). 모르는 키는 서버 이름 그대로(`data-server`). */
function stripName(key: string, label: string, transform?: string) {
  const ko = IND_KR[key];
  if (!ko) return <span data-server>{label}</span>;
  return <>{ko}{transform === "yoy" ? <em> 전년 대비</em> : null}</>;
}

// ── 사이클 띠: 지표 × 달 색 띠 ──
export function CycleStripGrid({ data }: { data: CycleStrips }) {
  const [cur, setCur] = useState<string | null>(null);
  if (!data.indicators.length) return <div className="mc-empty-sm">띠를 표시할 지표 없음</div>;
  const months = data.months;
  const say = (label: string, i: number, z: number | null) => `${ym(months[i])} · ${label} · z ${z == null ? "N/A" : signed(z)}`;
  return (
    <div className="mv-strips">
      {data.indicators.map((row) => {
        const nameTxt = (IND_KR[row.key] ? `${IND_KR[row.key]}${row.transform === "yoy" ? " 전년 대비" : ""}` : row.label);
        const last = row.cells.length - 1;
        return (
          <div key={row.key} className="mv-strip-row" tabIndex={0} role="group"
               aria-label={`${nameTxt}: ${ym(months[0])} z ${signed(row.cells[0])}, 현재 z ${signed(row.cells[last])}`}
               onFocus={() => setCur(say(nameTxt, last, row.cells[last]))}>
            <span className="mv-strip-lbl">{stripName(row.key, row.label, row.transform)}</span>
            <div className="mv-strip-cells">
              {row.cells.map((z, i) => (
                <i key={i} style={{ background: zFill(z) }} onMouseEnter={() => setCur(say(nameTxt, i, z))} />
              ))}
            </div>
            <b className="mv-strip-now">{row.cells[last] == null ? "N/A" : signed(row.cells[last], 1)}</b>
          </div>
        );
      })}
      <div className="mv-strip-axis" aria-hidden>
        <span>{ym(months[0])}</span><span>{ym(months[Math.floor(months.length / 2)])}</span><span>{ym(months.at(-1))}</span>
      </div>
      <LevelLegend lo="평균 하회" hi="평균 상회" />
      <p className="mc-readout" aria-live="polite">{cur ?? "칸에 마우스를 올리거나 줄을 Tab 으로 선택하면 여기에 값을 표시합니다"}</p>
    </div>
  );
}

/** 수준 색 범례 — 청록 ← 회색 → 주황. */
export function LevelLegend({ lo, hi }: { lo: string; hi: string }) {
  return (
    <div className="mc-zlegend"><span>{lo}</span><i className="mc-zleg-grad" aria-hidden /><span>{hi}</span></div>
  );
}

export const AxisStackChart = lazyChart(loadVisualCharts, (m) => m.AxisStackChart, { height: 210, label: "축 구성" });   // 본문은 visualParts.charts.tsx(화면이 뜬 뒤에 받는다)

// ── 자산군 가격 위치 띠(지난 5년 중 몇 백분위) ──
export function AssetStripGrid({ data }: { data: AssetStrips }) {
  const [cur, setCur] = useState<string | null>(null);
  if (!data.assets.length) return <div className="mc-empty-sm">자산 시세가 아직 없습니다(ETF 시세를 적재하면 표시됩니다)</div>;
  const say = (label: string, i: number, n: number, p: number | null) => `${label} · ${n - i}달 전${i === n - 1 ? "(지금)" : ""} · ${p == null ? "N/A" : `지난 5년 중 ${p}%`}`;
  return (
    <div className="mv-strips">
      {data.assets.map((a) => {
        const n = a.cells.length;
        return (
          <div key={a.ticker} className="mv-strip-row" tabIndex={0} role="group"
               aria-label={`${a.label}: 현재 최근 5년 백분위 ${a.now == null ? "N/A" : `${a.now}%`}`}
               onFocus={() => setCur(say(a.label, n - 1, n, a.cells[n - 1]))}>
            <span className="mv-strip-lbl">{a.label} <em data-mono>{a.ticker}</em></span>
            <div className="mv-strip-cells">
              {a.cells.map((p, i) => (
                <i key={i} style={{ background: pctFill(p) }} onMouseEnter={() => setCur(say(a.label, i, n, p))} />
              ))}
            </div>
            <b className="mv-strip-now">{a.now == null ? "N/A" : `${a.now}%`}</b>
          </div>
        );
      })}
      <LevelLegend lo="최근 5년 중 가격이 낮은 구간" hi="높은 구간" />
      <p className="mc-readout" aria-live="polite">{cur ?? "칸에 마우스를 올리거나 줄을 Tab 으로 선택하면 여기에 값을 표시합니다"}</p>
    </div>
  );
}

// ── 한국 · 미국 비교 표(같은 방식으로 바꾼 z) ──
export function KrUsCompareTable({ data }: { data: KrUsCompare }) {
  if (!data.rows.length) return <div className="mc-empty-sm">비교할 지표 없음</div>;
  const cell = (z: number | null) => (
    <td><span className="mc-zcell" style={{ background: zFill(z) }}>{z == null ? "N/A" : signed(z)}</span></td>
  );
  return (
    <div className="mc-tablewrap">
      <table className="mv-cmp">
        <thead><tr><th>지표</th><th>한국</th><th>미국</th><th>한국 − 미국</th></tr></thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.label}>
              <td data-server>{r.label}</td>
              {cell(r.kr)}{cell(r.us)}
              <td>{r.gap == null ? "N/A" : signed(r.gap)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
