"use client";
// 기업 분석의 차트 넷 — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 본문은 parts.tsx(PriceChart·PriceValueChart·KpiBars)와 MoneySection.tsx(StoryChart)에 있던 그대로다. 소비자는 그 파일들이 같은 이름으로 내보내는 것을 쓴다.
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, ComposedChart, Line, AreaChart, Area,
} from "recharts";
import type { CompanyData } from "@/entities/company/insightsModel";
import { won, eok } from "@/entities/company/insightsModel";
import { useChartAnimation, TX_TIP_STYLE, TX_TIP_STYLE as TIP_STYLE } from "@/shared/ui/chartStyle";
import { AXIS_TICK, BAR_TOP, MARK, ringDot } from "@/shared/ui/chart/chartSpec";
import { catColor } from "@/shared/ui/vizColor";
import type { ValueBandIn } from "./parts";
import { margin, type Row } from "./MoneySection";
import { eokWon, pctTxt, periodKo, periodShort } from "./fmt";

const AXIS = AXIS_TICK;

/** 1년 주가 면적 — 중립 한 색(판정 색으로 칠하지 않는다) + 내재가치 점선. ★주가가 없으면 부르지 않는다(지어내지 않음)★. */
export function PriceChart({ data, height = 200, intrinsic }: { data: CompanyData["price1y"]; height?: number; intrinsic?: number }) {
  const anim = useChartAnimation();
  const tick = (v: number) => (v >= 10000 ? `${Math.round(v / 1000).toLocaleString()}천` : Math.round(v).toLocaleString());
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <XAxis dataKey="t" tick={AXIS} interval={Math.max(0, Math.floor(data.length / 6))} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
        <YAxis domain={["dataMin", "dataMax"]} tick={AXIS} tickFormatter={tick} width={48} tickLine={false} axisLine={false} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(v: number) => [won(v), "종가"]} />
        {intrinsic ? <ReferenceLine y={intrinsic} stroke="var(--tx-ink)" strokeDasharray="5 4" strokeWidth={1.2} ifOverflow="extendDomain" /> : null}
        <Area isAnimationActive={anim} type="monotone" dataKey="p" stroke="var(--tx-blue)" strokeWidth={MARK.line} fill="var(--tx-blue)" fillOpacity={MARK.wash} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** 1년 주가 선 뒤에 모형별 가치 범위(풋볼필드 lo~hi)를 가로 띠로 깔고 내재가치 점선을 긋는다.
 *  ★주가가 없으면 선을 그리지 않는다(지어내지 않음)★ — 띠만 남고 부르는 쪽이 "시세가 아직…"을 말한다.
 *  현재가와 극단 괴리(4배↑·0.15배↓) 밴드는 축을 뭉개지 않게 그림 밖 목록으로(풋볼필드와 같은 규칙). */
export function PriceValueChart({ data, price, intrinsic, bands, height = 260 }: {
  data: CompanyData["price1y"]; price: number; intrinsic: number; bands: ValueBandIn[]; height?: number;
}) {
  const anim = useChartAnimation();
  const inRange = bands.filter((b) => b.lo <= price * 4 && b.hi >= price * 0.15);
  const out = bands.filter((b) => !inRange.includes(b));
  const vals = [...data.map((d) => d.p), ...inRange.flatMap((b) => [b.lo, b.hi]), price, ...(intrinsic > 0 ? [intrinsic] : [])].filter((v) => v > 0);
  const lo = Math.min(...vals) * 0.94, hi = Math.max(...vals) * 1.06;
  const rows = data.length ? data : [{ t: "지금", p: null as unknown as number }];
  const tick = (v: number) => (v >= 10000 ? `${Math.round(v / 1000).toLocaleString()}천` : Math.round(v).toLocaleString());
  return (
    <div className="ci-pv">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <XAxis dataKey="t" tick={AXIS} interval={Math.max(0, Math.floor(rows.length / 6))} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
          <YAxis domain={[lo, hi]} tick={AXIS} tickFormatter={tick} width={48} tickLine={false} axisLine={false} />
          {inRange.map((b, i) => (
            <ReferenceArea key={b.id} y1={b.lo} y2={Math.max(b.hi, b.lo * 1.002)} fill={catColor(i)} fillOpacity={0.22} stroke={catColor(i)} strokeOpacity={0.6} ifOverflow="extendDomain" />
          ))}
          {intrinsic > 0 && <ReferenceLine y={intrinsic} stroke="var(--tx-ink)" strokeDasharray="5 4" strokeWidth={1.2} />}
          {data.length > 0 && <Tooltip contentStyle={TIP_STYLE} formatter={(v: number) => [won(v), "종가"]} />}
          {data.length > 0 && <Line type="monotone" dataKey="p" stroke="var(--tx-blue)" strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />}
        </ComposedChart>
      </ResponsiveContainer>
      <ul className="ci-pv-leg">
        {inRange.map((b, i) => (
          <li key={b.id}><i style={{ background: catColor(i) }} aria-hidden /><span data-server>{b.label}</span> <b>{won(b.lo)}~{won(b.hi)}</b></li>
        ))}
      </ul>
      <p className="ci-pv-key">
        {data.length > 0 && <span><i className="ci-pv-sw line" aria-hidden />주가(1년)</span>}
        {intrinsic > 0 && <span><i className="ci-pv-sw dash" aria-hidden />내재가치 {won(intrinsic)}</span>}
      </p>
      {out.length > 0 && (
        <ul className="ci-pv-out" aria-label="그림 범위 밖 가치">
          {out.map((b) => <li key={b.id}><span data-server>{b.label}</span> {won(b.lo)}~{won(b.hi)}: 현재가와 너무 멀어 그림 밖에 적었어요(원천 자료를 확인해 보세요)</li>)}
        </ul>
      )}
    </div>
  );
}

/** 기간별 막대 — ★중립 한 색★(BU6b: 옛 화면은 마지막 해만 파랑이었는데 뜻이 없었다). 값이 없는 기간(null)은 막대가 비고 0 을 그리지 않는다. */
export function KpiBars({ data, dataKey, xKey = "year", height = 130, fmt = eok }: { data: ReadonlyArray<object>; dataKey: string; xKey?: string; color?: string; height?: number; fmt?: (n: number) => string }) {
  const anim = useChartAnimation();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data as unknown[]} margin={{ top: 14, right: 4, bottom: 0, left: 4 }}>
        <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
        <ReferenceLine y={0} stroke="var(--tx-mute)" />
        <Tooltip formatter={(v: number) => [fmt(v), ""]} contentStyle={TIP_STYLE} cursor={{ fill: "var(--tx-soft)" }} />
        <Bar isAnimationActive={anim} dataKey={dataKey} radius={BAR_TOP} maxBarSize={MARK.barMax} fill="var(--tx-blue)" />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StoryChart({ rows }: { rows: Row[] }) {
  const anim = useChartAnimation();
  const data = rows.map((r) => ({ k: periodShort(r.k), revenue: r.revenue, opM: r.opMargin, niM: margin(r.ni, r.revenue) }));
  const tickEok = (v: number) => (Math.abs(v) >= 10000 ? `${Math.round(v / 10000).toLocaleString("ko-KR")}조` : `${Math.round(v).toLocaleString("ko-KR")}억`);
  const AX = AXIS_TICK;
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
          <Bar yAxisId="w" dataKey="revenue" fill="var(--tx-blue)" radius={BAR_TOP} maxBarSize={MARK.barMax} isAnimationActive={anim} />
          <Line yAxisId="p" dataKey="opM" stroke={catColor(1)} strokeWidth={MARK.line} dot={ringDot(catColor(1))} connectNulls={false} isAnimationActive={anim} />
          <Line yAxisId="p" dataKey="niM" stroke={catColor(6)} strokeWidth={MARK.quiet} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={anim} />
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
