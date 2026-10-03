"use client";
// visualParts — 사이클 띠 · 축 하위요인 쌓기 · 자산군 가격 위치 띠 · 한국/미국 비교 표
//   (BU5a: 머리의 도넛 카드·브리핑 문장은 답 한 문장으로 바뀌어 지웠다. BU5a+ 에서 도넛은 `RegimeVisual` 로 다시 지었다.)
// BU5b: 띠·표 칸은 수준 색(주황/청록) · 툴팁 대신 보이는 읽기 줄(칸에 올리거나 줄에 초점) · 쌓기 차트에 범례를 붙였다
//   (예전엔 여섯 색이 무엇인지 화면 어디에도 없었다) · 국기 이모지·고정폭 걷음. 그림은 하나도 지우지 않았다.
import React, { useState } from "react";
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ReferenceLine,
} from "recharts";
import type { AssetStrips, AxisHistory, CycleStrips, KrUsCompare } from "@/entities/macro/analysisModel";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { IND_KR, catColor, pctFill, signed, ym, zFill } from "./macroKo";
import { TIP_STYLE } from "./cockpitParts";

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
  if (!data.indicators.length) return <div className="mc-empty-sm">띠를 그릴 지표가 없어요</div>;
  const months = data.months;
  const say = (label: string, i: number, z: number | null) => `${ym(months[i])} · ${label} · z ${z == null ? "몰라요" : signed(z)}`;
  return (
    <div className="mv-strips">
      {data.indicators.map((row) => {
        const nameTxt = (IND_KR[row.key] ? `${IND_KR[row.key]}${row.transform === "yoy" ? " 전년 대비" : ""}` : row.label);
        const last = row.cells.length - 1;
        return (
          <div key={row.key} className="mv-strip-row" tabIndex={0} role="group"
               aria-label={`${nameTxt}: ${ym(months[0])} z ${signed(row.cells[0])}, 지금 z ${signed(row.cells[last])}`}
               onFocus={() => setCur(say(nameTxt, last, row.cells[last]))}>
            <span className="mv-strip-lbl">{stripName(row.key, row.label, row.transform)}</span>
            <div className="mv-strip-cells">
              {row.cells.map((z, i) => (
                <i key={i} style={{ background: zFill(z) }} onMouseEnter={() => setCur(say(nameTxt, i, z))} />
              ))}
            </div>
            <b className="mv-strip-now">{row.cells[last] == null ? "몰라요" : signed(row.cells[last], 1)}</b>
          </div>
        );
      })}
      <div className="mv-strip-axis" aria-hidden>
        <span>{ym(months[0])}</span><span>{ym(months[Math.floor(months.length / 2)])}</span><span>{ym(months.at(-1))}</span>
      </div>
      <LevelLegend lo="평균보다 낮아요" hi="평균보다 높아요" />
      <p className="mc-readout" aria-live="polite">{cur ?? "칸에 마우스를 올리거나 줄을 Tab 으로 고르면 여기에 값이 나와요"}</p>
    </div>
  );
}

/** 수준 색 범례 — 청록 ← 회색 → 주황. */
export function LevelLegend({ lo, hi }: { lo: string; hi: string }) {
  return (
    <div className="mc-zlegend"><span>{lo}</span><i className="mc-zleg-grad" aria-hidden /><span>{hi}</span></div>
  );
}

// ── 축 하위요인: 축 점수 = 지표 기여 쌓기(막대) + 축 점수(선) ──
export function AxisStackChart({ hist, axis }: { hist: AxisHistory; axis: "growth" | "inflation" }) {
  const anim = useChartAnimation();
  const partsKey = axis === "growth" ? "growth_parts" : "inflation_parts";
  const keys = Array.from(new Set(hist.points.flatMap((p) => Object.keys(p[partsKey] ?? {}))));
  const data = hist.points.map((p) => ({
    t: ym(p.t), score: p[axis],
    ...Object.fromEntries(keys.map((k) => [k, p[partsKey]?.[k] ?? 0])),
  }));
  const axisName = axis === "growth" ? "성장 축" : "물가 축";
  return (
    <div className="mc-axstack">
      <ResponsiveContainer width="100%" height={210}>
        <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -14 }} stackOffset="sign">
          <XAxis dataKey="t" tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" interval={Math.max(0, Math.floor(data.length / 5))} />
          <YAxis tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" />
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          <Tooltip contentStyle={TIP_STYLE} formatter={(v: number | string, name: string) => [signed(Number(v), 3), IND_KR[name] ?? (name === "score" ? axisName : name)]} />
          {keys.map((k, i) => (
            <Bar key={k} dataKey={k} stackId="s" fill={catColor(i)} isAnimationActive={anim} />
          ))}
          <Line dataKey="score" stroke="var(--tx-ink)" strokeWidth={2} dot={false} isAnimationActive={anim} name="score" />
        </ComposedChart>
      </ResponsiveContainer>
      <ul className="mc-legend">
        {keys.map((k, i) => <li key={k}><i style={{ background: catColor(i) }} aria-hidden />{IND_KR[k] ?? k}</li>)}
        <li><i className="mc-legend-line" aria-hidden />{axisName} 점수</li>
      </ul>
    </div>
  );
}

// ── 자산군 가격 위치 띠(지난 5년 중 몇 백분위) ──
export function AssetStripGrid({ data }: { data: AssetStrips }) {
  const [cur, setCur] = useState<string | null>(null);
  if (!data.assets.length) return <div className="mc-empty-sm">자산 시세가 아직 없어요(ETF 시세를 적재하면 보여요)</div>;
  const say = (label: string, i: number, n: number, p: number | null) => `${label} · ${n - i}달 전${i === n - 1 ? "(지금)" : ""} · ${p == null ? "몰라요" : `지난 5년 중 ${p}%`}`;
  return (
    <div className="mv-strips">
      {data.assets.map((a) => {
        const n = a.cells.length;
        return (
          <div key={a.ticker} className="mv-strip-row" tabIndex={0} role="group"
               aria-label={`${a.label}: 지금 지난 5년 중 ${a.now == null ? "몰라요" : `${a.now}%`}`}
               onFocus={() => setCur(say(a.label, n - 1, n, a.cells[n - 1]))}>
            <span className="mv-strip-lbl">{a.label} <em data-mono>{a.ticker}</em></span>
            <div className="mv-strip-cells">
              {a.cells.map((p, i) => (
                <i key={i} style={{ background: pctFill(p) }} onMouseEnter={() => setCur(say(a.label, i, n, p))} />
              ))}
            </div>
            <b className="mv-strip-now">{a.now == null ? "몰라요" : `${a.now}%`}</b>
          </div>
        );
      })}
      <LevelLegend lo="지난 5년 중 가격이 낮은 편" hi="높은 편" />
      <p className="mc-readout" aria-live="polite">{cur ?? "칸에 마우스를 올리거나 줄을 Tab 으로 고르면 여기에 값이 나와요"}</p>
    </div>
  );
}

// ── 한국 · 미국 비교 표(같은 방식으로 바꾼 z) ──
export function KrUsCompareTable({ data }: { data: KrUsCompare }) {
  if (!data.rows.length) return <div className="mc-empty-sm">비교할 지표가 없어요</div>;
  const cell = (z: number | null) => (
    <td><span className="mc-zcell" style={{ background: zFill(z) }}>{z == null ? "몰라요" : signed(z)}</span></td>
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
              <td>{r.gap == null ? "몰라요" : signed(r.gap)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
