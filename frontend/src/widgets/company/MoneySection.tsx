"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 돈 버는 힘(BU6b · 사용자 결정 "이야기 그림 먼저 + 표는 펼침")
// ─────────────────────────────────────────────────────────────────────────────
// 위에서 아래로: 답 한 문장(서버 매출 첫·마지막 해) → ★이야기 그림★(매출 막대 + 영업이익률 선 + 순이익률 점선) →
//   요약 카드 셋(ROE·부채비율·주당배당금: 마지막 값 + 지난 기간 대비 + 추세) → "표로 보기"(9줄 표 + 막대 셋, 기본 닫힘) → 재무 심화.
// ★그림은 지우지 않았다★ 옛 표·막대 셋은 그대로 펼침 안에 있다(사용자 규칙 2). 이야기 그림과 카드는 더한 것.
//   막대 셋의 카드는 `.ca-cp-card` 가 아니라 `.ci-kpicard` — 닫힌 펼침 안이라 module-motion 04 패널(숨김 0 검사)에서 뺀다.
// 숫자는 서버 값 그대로 — 화면은 이익률(영업이익÷매출 · 순이익÷매출) 나눗셈과 서식만 한다(새 판단 없음).
// ★null = 몰라요★ 서버가 비운 해는 막대·점이 비고 표에는 "몰라요"(0 을 그리지 않는다). 옛 표 머리 "항목(억원)" 은 값이 조·원·% 로
//   섞여 있어 거짓 단위였다 — 머리는 "항목", 단위는 칸마다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ReferenceLine } from "recharts";
import type { CompanyData } from "@/entities/company/insightsModel";
import { RetryFail } from "@/shared/ui/tx";
import { useChartAnimation, TX_TIP_STYLE } from "@/shared/ui/chartStyle";
import { catColor } from "@/shared/ui/vizColor";
import { KpiBars, Spark } from "./parts";
import FinancialsDeepTab from "./FinancialsDeepTab";
import { eokWon, ok, pctTxt, ppSigned, periodKo, periodShort, wonTxt } from "./fmt";

type N = number | null;
type Row = { k: string; revenue: N; op: N; ni: N; equity: N; roe: N; debt: N; opMargin: N; eps: N; bps: N; dps: N };
const margin = (a: N, rev: N): N => (ok(a) && ok(rev) && rev !== 0 ? Math.round((a / rev) * 1000) / 10 : null);

function rowsOf(c: CompanyData, mode: "annual" | "quarter"): Row[] {
  if (mode === "quarter") return c.quarters.map((q) => ({ k: q.q, revenue: q.revenue, op: q.op, ni: q.ni, equity: q.equity, roe: q.roe, debt: q.debt, opMargin: q.opMargin, eps: q.eps, bps: q.bps, dps: q.dps }));
  return c.years.map((y) => ({ k: y.year, revenue: y.revenue, op: y.op, ni: y.ni, equity: y.equity, roe: y.roe, debt: y.debt, opMargin: margin(y.op, y.revenue), eps: y.eps, bps: y.bps, dps: y.dps }));
}

/** 답 한 문장 — 매출을 아는 첫 기간과 마지막 기간(서버 값). 둘이 없으면 흐름을 말하지 않는다. */
function answer(rows: Row[]): string {
  const known = rows.filter((r) => ok(r.revenue));
  if (known.length < 2) return "매출을 두 기간 이상 받지 못해 흐름을 말할 수 없어요.";
  const a = known[0], b = known[known.length - 1];
  const verb = (b.revenue as number) > (a.revenue as number) ? "늘었어요" : (b.revenue as number) < (a.revenue as number) ? "줄었어요" : "같았어요";
  const m = ok(b.opMargin) ? ` ${periodKo(b.k)} 영업이익률은 ${pctTxt(b.opMargin)}예요.` : "";
  return `매출은 ${periodKo(a.k)} ${eokWon(a.revenue)}에서 ${periodKo(b.k)} ${eokWon(b.revenue)}으로 ${verb}.${m}`;
}

function StoryChart({ rows }: { rows: Row[] }) {
  const anim = useChartAnimation();
  const data = rows.map((r) => ({ k: periodShort(r.k), revenue: r.revenue, opM: r.opMargin, niM: margin(r.ni, r.revenue) }));
  const tickEok = (v: number) => (Math.abs(v) >= 10000 ? `${Math.round(v / 10000).toLocaleString("ko-KR")}조` : `${Math.round(v).toLocaleString("ko-KR")}억`);
  const AX = { fontSize: 11, fill: "var(--tx-sub)" };
  return (
    <figure className="ci-story" aria-label={`기간별 매출과 이익률: ${rows.map((r) => `${periodKo(r.k)} 매출 ${eokWon(r.revenue)}, 영업이익률 ${pctTxt(r.opMargin)}`).join(", ")}`}>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 10, right: 4, bottom: 0, left: 0 }}>
          <XAxis dataKey="k" tick={AX} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
          <YAxis yAxisId="w" tick={AX} tickFormatter={tickEok} width={52} tickLine={false} axisLine={false} />
          <YAxis yAxisId="p" orientation="right" tick={AX} tickFormatter={(v: number) => `${v}%`} width={40} tickLine={false} axisLine={false} />
          <ReferenceLine yAxisId="p" y={0} stroke="var(--tx-line)" />
          <Tooltip contentStyle={TX_TIP_STYLE} cursor={{ fill: "var(--tx-soft)" }}
                   formatter={(v: number, name: string) => [name === "revenue" ? eokWon(v) : pctTxt(v), name === "revenue" ? "매출" : name === "opM" ? "영업이익률" : "순이익률"]} />
          <Bar yAxisId="w" dataKey="revenue" fill="var(--tx-blue)" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={anim} />
          <Line yAxisId="p" dataKey="opM" stroke={catColor(1)} strokeWidth={2.2} dot={{ r: 3, fill: catColor(1), strokeWidth: 0 }} connectNulls={false} isAnimationActive={anim} />
          <Line yAxisId="p" dataKey="niM" stroke={catColor(6)} strokeWidth={1.8} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={anim} />
        </ComposedChart>
      </ResponsiveContainer>
      <figcaption className="ci-story-cap">
        <span className="ci-story-key"><i className="sw bar" aria-hidden />매출(막대 · 왼쪽 눈금)</span>
        <span className="ci-story-key"><i className="sw op" aria-hidden />영업이익률(선 · 오른쪽 눈금)</span>
        <span className="ci-story-key"><i className="sw ni" aria-hidden />순이익률(점선)</span>
      </figcaption>
    </figure>
  );
}

/** 요약 카드 — 마지막 값 + 바로 전 기간 대비(등락은 부호 + 한국식 등락색) + 추세. 두 값 중 하나라도 모르면 대비를 그리지 않는다. */
function SumCard({ k, label, vals, periods, fmt, delta }: { k: string; label: string; vals: N[]; periods: string[]; fmt: (v: N) => string; delta: (d: number) => string }) {
  const last = vals.length - 1;
  const v = vals[last] ?? null, p = last > 0 ? vals[last - 1] : null;
  const d = ok(v) && ok(p) ? v - p : null;
  const dir = d == null ? undefined : d > 0 ? "up" : d < 0 ? "down" : "flat";
  return (
    <div className="ci-sumcard" data-k={k}>
      <span className="ci-sumcard-k">{label}</span>
      <b className="ci-sumcard-v">{fmt(v)}</b>
      <span className="ci-sumcard-d" data-dir={dir}>{d == null ? "바로 전 기간과 비교할 수 없어요" : `${periodKo(periods[last - 1])}보다 ${delta(d)}`}</span>
      <Spark values={vals} w={120} h={30} />
    </div>
  );
}

function FinTable({ rows, quarter }: { rows: Row[]; quarter: boolean }) {
  const lines: [string, N[], (v: N) => string][] = [
    ["매출", rows.map((r) => r.revenue), eokWon],
    ["영업이익", rows.map((r) => r.op), eokWon],
    ["순이익", rows.map((r) => r.ni), eokWon],
    ["자기자본", rows.map((r) => r.equity), eokWon],
    ["ROE(자기자본이익률)", rows.map((r) => r.roe), (v) => pctTxt(v)],
    ["부채비율", rows.map((r) => r.debt), (v) => pctTxt(v)],
    ...(quarter ? [["영업이익률", rows.map((r) => r.opMargin), (v: N) => pctTxt(v)] as [string, N[], (v: N) => string]] : []),
    ["주당순이익(EPS)", rows.map((r) => r.eps), wonTxt],
    ["주당순자산(BPS)", rows.map((r) => r.bps), wonTxt],
    ["주당배당금(DPS)", rows.map((r) => r.dps), wonTxt],
  ];
  return (
    <div className="ci-tablewrap">
      <table className="ca-cp-fin">
        <thead><tr><th scope="col">항목</th>{rows.map((r) => <th key={r.k} scope="col">{periodShort(r.k)}</th>)}<th scope="col">추세</th></tr></thead>
        <tbody>
          {lines.map(([lbl, vals, f]) => (
            <tr key={lbl}><td className="lbl">{lbl}</td>{vals.map((v, i) => <td key={i} data-unknown={ok(v) ? undefined : ""}>{f(v)}</td>)}<td className="spark"><Spark values={vals} /></td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MoneySection({ c, onRetry, seen }: { c: CompanyData; onRetry: () => void; seen: boolean }) {
  const [mode, setMode] = useState<"annual" | "quarter">("annual");
  const q = mode === "quarter" && c.quarters.length > 0;
  const rows = rowsOf(c, q ? "quarter" : "annual");
  const unit = q ? "분기" : "해";
  return (
    <div className="ca-cp-pad ci-money">
      {c.years.length ? (
        <>
          <p className="ci-money-ans">{answer(rowsOf(c, "annual"))}</p>
          <div className="ca-cp-fintabs" role="group" aria-label="기간 단위">
            <button type="button" aria-pressed={!q} className={!q ? "on" : ""} onClick={() => setMode("annual")}>연도</button>
            <button type="button" aria-pressed={q} className={q ? "on" : ""} disabled={!c.quarters.length} onClick={() => c.quarters.length && setMode("quarter")}>분기</button>
            {!c.quarters.length && !c.failed.includes("quarters") && <span className="ci-note">분기 자료가 없어요(전자공시 분기보고서가 적재되면 켜져요)</span>}
          </div>
          {c.failed.includes("quarters") && <RetryFail title="분기 재무를 불러오지 못했어요" onRetry={onRetry} />}
          <StoryChart rows={rows} />
          <div className="ci-money-cards">
            <SumCard k="roe" label="ROE(자기자본이익률)" vals={rows.map((r) => r.roe)} periods={rows.map((r) => r.k)} fmt={(v) => pctTxt(v)} delta={(d) => ppSigned(d, 1)} />
            <SumCard k="debt" label="부채비율" vals={rows.map((r) => r.debt)} periods={rows.map((r) => r.k)} fmt={(v) => pctTxt(v)} delta={(d) => ppSigned(d, 1)} />
            <SumCard k="dps" label="주당배당금" vals={rows.map((r) => r.dps)} periods={rows.map((r) => r.k)} fmt={wonTxt} delta={(d) => `${d > 0 ? "+" : ""}${wonTxt(d)}`} />
          </div>
          <details className="ci-fin-more">
            <summary>표로 보기(항목 {q ? 10 : 9}줄 × {rows.length}{unit})</summary>
            <FinTable rows={rows} quarter={q} />
            <div className="ca-cp-kpibars">
              <div className="ci-kpicard"><div className="ci-kpicard-h">매출</div><KpiBars data={rows} dataKey="revenue" xKey="k" fmt={eokWon} /></div>
              <div className="ci-kpicard"><div className="ci-kpicard-h">영업이익</div><KpiBars data={rows} dataKey="op" xKey="k" fmt={eokWon} /></div>
              <div className="ci-kpicard"><div className="ci-kpicard-h">순이익</div><KpiBars data={rows} dataKey="ni" xKey="k" fmt={eokWon} /></div>
            </div>
          </details>
        </>
      ) : c.failed.includes("financials")
        ? <RetryFail title="재무 시계열을 불러오지 못했어요" onRetry={onRetry} />
        : <p className="ca-cp-empty">재무 시계열 자료가 없어요(전자공시에 없는 종목일 수 있어요).</p>}
      {seen && <FinancialsDeepTab code={c.code} />}
    </div>
  );
}
