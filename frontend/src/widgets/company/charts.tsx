"use client";
// 기업 분석의 차트 넷 — `lazyChart` 로 ★화면이 뜬 뒤에★ 받는다(recharts 를 첫 화면 JS 에서 뺌 · 2026-11-08 · `e2e/charts-lazy.spec.ts`).
// 소비자는 parts.tsx(PriceChart·PriceValueChart·KpiBars)와 MoneySection.tsx(StoryChart)가 같은 이름으로 내보내는 것을 쓴다.
// ★2026-11-10 (ADR 004 §6 · 설계 `2026-11-10-chart-indicator-system-design.md`)★
//   · 값은 호버 툴팁이 아니라 늘 보이는 읽는 줄(+ 표 쌍둥이)에 — 처음 자리 = 마지막 점 · ←→ Home End · 마우스를 올려도 옮겨진다.
//   · 이야기 그림은 이중 축이 아니다 — 매출(원)과 이익률(%)을 위아래 두 칸으로(같은 기간 축).
//   · 주가와 가치는 겹친 띠가 아니다 — 모형별 범위는 주가 선 오른쪽의 겹치지 않는 가는 막대(같은 y 축).
//   · 주가 선은 ★서버 종가 그대로★다(예전에는 지금 주가에 맞춰 통째로 옮겨 그렸다 — entities/company/data.ts::mapPrices). 지금 주가(헤더 가격)는
//     범위 칸을 가로지르는 따로 선(`.ci-pv-nowline`)과 글자(`.ci-pv-now`)로 — 마지막 종가와 다르면 다르게 보인다.
import { useMemo, useRef } from "react";
import {
  BarChart, Bar, XAxis, YAxis, ResponsiveContainer, ReferenceLine, ReferenceArea, ReferenceDot, ComposedChart, Line, AreaChart, Area,
} from "recharts";
import type { CompanyData } from "@/entities/company/insightsModel";
import { won, eok } from "@/entities/company/insightsModel";
import { ReadoutFrame, followChart, useReadout, xFromChartEvent, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { AXIS_TICK, BAR_TOP, CROSSHAIR, MARK, pickDot, ringDot } from "@/shared/ui/chart/chartSpec";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";
import { catColor } from "@/shared/ui/vizColor";
import type { ValueBandIn } from "./parts";
import { margin, type Row } from "./MoneySection";
import { eokWon, pctTxt, periodKo, periodShort } from "./fmt";

type Price = CompanyData["price1y"];
const AXIS = AXIS_TICK;
const BLUE = "var(--tx-blue)";
const priceTick = (v: number) => (v >= 10000 ? `${Math.round(v / 1000).toLocaleString()}천` : Math.round(v).toLocaleString());

/** 주가의 읽는 줄 — 머리 = 서버 날짜(없으면 축 글자), 값 = 서버 종가(그림의 높이와 같은 값). */
const priceRows = (data: Price): ReadRow[] => data.map((d) => ({
  head: d.date ? d.date.replace(/-/g, ".") : d.t,
  cells: [{ key: "p", label: "종가", text: won(d.p) }],
}));

/** 1년 주가 면적 — 중립 한 색(판정 색으로 칠하지 않는다) + 내재가치 점선. ★주가가 없으면 부르지 않는다(지어내지 않음)★. */
export function PriceChart({ data, height = 200, intrinsic }: { data: Price; height?: number; intrinsic?: number }) {
  const anim = useChartAnimation();
  // 가로축은 점의 차례(i) — 축 글자(연.월)는 여러 점이 같아 자리를 가리킬 수 없다.
  const pts = useMemo(() => data.map((d, i) => ({ i, p: d.p })), [data]);
  const rows = priceRows(data);
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  const cur = idx >= 0 ? pts[idx] : null;
  return (
    <ReadoutFrame id="price-1y" label="1년 주가" headLabel="날짜" rows={rows} idx={idx} onKeyDown={onKeyDown}>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={pts} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} onMouseMove={followChart(setIdx)}>
          <XAxis dataKey="i" tick={AXIS} tickFormatter={(i: number) => data[i]?.t ?? ""} interval={Math.max(0, Math.floor(data.length / 6))} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
          <YAxis domain={["dataMin", "dataMax"]} tick={AXIS} tickFormatter={priceTick} width={48} tickLine={false} axisLine={false} />
          {intrinsic ? <ReferenceLine y={intrinsic} stroke="var(--tx-ink)" strokeDasharray="5 4" strokeWidth={1.2} ifOverflow="extendDomain" /> : null}
          <Area isAnimationActive={anim} type="monotone" dataKey="p" stroke={BLUE} strokeWidth={MARK.line} fill={BLUE} fillOpacity={MARK.wash} />
          {cur && <ReferenceLine x={cur.i} {...CROSSHAIR} />}
          {cur && <ReferenceDot x={cur.i} y={cur.p} {...pickDot(BLUE)} />}
        </AreaChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

/** 주가 선(왼쪽 구역 · 서버 종가 그대로) + 모형별 가치 범위 막대(오른쪽 구역 · 풋볼필드 lo~hi) + 내재가치 점선 + ★지금 주가 선★(헤더 가격 `price` —
 *  범위 칸을 가로지른다 · 시세 이력의 마지막 종가와 출처가 달라 높이가 다를 수 있고, 다르면 다르게 보인다). ★y 축은 하나★라 셋을 같은 눈금으로 견준다.
 *  예전에는 범위를 반투명 띠로 겹쳐 깔아 겹친 곳이 범례에 없는 색이 됐다 — 막대는 서로 겹치지 않는다.
 *  가로는 그림 px 단위의 숫자 축(잰 폭)이라 막대 폭이 화면 폭과 상관없이 규격대로다.
 *  ★주가가 없으면 선을 그리지 않는다(지어내지 않음)★ — 막대만 남고 부르는 쪽이 "시세가 아직…"을 말한다.
 *  현재가와 극단 괴리(4배↑·0.15배↓) 밴드는 축을 뭉개지 않게 그림 밖 목록으로(풋볼필드와 같은 규칙). */
const PV_YW = 48, PV_MR = 12;       // y 축 폭 · 오른쪽 여백(px)
export function PriceValueChart({ data, price, intrinsic, bands, height = 260 }: {
  data: Price; price: number; intrinsic: number; bands: ValueBandIn[]; height?: number;
}) {
  const anim = useChartAnimation();
  const boxRef = useRef<HTMLDivElement>(null);
  const plotW = Math.max(160, useMeasuredWidth(boxRef, 640) - PV_YW - PV_MR);
  const inRange = bands.filter((b) => b.lo <= price * 4 && b.hi >= price * 0.15);
  const out = bands.filter((b) => !inRange.includes(b));
  const vals = [...data.map((d) => d.p), ...inRange.flatMap((b) => [b.lo, b.hi]), price, ...(intrinsic > 0 ? [intrinsic] : [])].filter((v) => v > 0);
  const lo = Math.min(...vals) * 0.94, hi = Math.max(...vals) * 1.06;
  const n = data.length, m = inRange.length, hasLine = n > 1;
  // 가로 나눔 — 선이 있으면 [선 구역 | 틈 | 막대 칸], 없으면 막대를 그림 폭에 고르게.
  const barW = hasLine ? (plotW >= 520 ? 10 : 6) : Math.min(MARK.barMax, 14);
  const gap = barW * 0.7, lead = 16;
  const gutter = hasLine && m ? lead + m * barW + (m - 1) * gap : 0;
  const lineW = hasLine ? plotW - gutter : 0;
  // 값이 한 점인 범위(lo = hi)도 보여야 한다 — 막대 폭만큼의 높이를 준다(둥근 점으로 보인다). 값은 범례에 그대로 있다.
  const minSpan = ((hi - lo) * barW) / Math.max(1, height - 38);
  const bandY = (b: ValueBandIn): [number, number] => (b.hi - b.lo >= minSpan ? [b.lo, b.hi] : [(b.lo + b.hi) / 2 - minSpan / 2, (b.lo + b.hi) / 2 + minSpan / 2]);
  const bandX = (k: number) => (hasLine ? lineW + lead + k * (barW + gap) : ((k + 0.5) * plotW) / Math.max(1, m) - barW / 2);
  const pts = useMemo(() => data.map((d, i) => ({ x: n > 1 ? (i / (n - 1)) * lineW : 0, p: d.p })), [data, n, lineW]);
  const every = Math.max(1, Math.floor(n / 6));
  const ticks = hasLine ? pts.filter((_, i) => i % every === 0).map((q) => q.x) : [];
  const labelAt = (x: number) => { const i = n > 1 ? Math.round((x / lineW) * (n - 1)) : 0; return data[i]?.t ?? ""; };
  const rows = priceRows(data);
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  const cur = hasLine && idx >= 0 ? pts[idx] : null;
  const last = hasLine ? pts[n - 1] : null;
  const onMove = (st: unknown) => {
    const x = xFromChartEvent(st);
    if (x === null || !hasLine) return;
    setIdx(Math.min(n - 1, Math.max(0, Math.round(((x - PV_YW) / lineW) * (n - 1)))));
  };
  const chart = (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={pts} margin={{ top: 8, right: PV_MR, bottom: 0, left: 0 }} onMouseMove={onMove}>
        <XAxis type="number" dataKey="x" domain={[0, plotW]} ticks={ticks} tickFormatter={labelAt} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} allowDataOverflow />
        <YAxis domain={[lo, hi]} tick={AXIS} tickFormatter={priceTick} width={PV_YW} tickLine={false} axisLine={false} />
        {inRange.map((b, k) => (
          <ReferenceArea key={b.id} x1={bandX(k)} x2={bandX(k) + barW} y1={bandY(b)[0]} y2={bandY(b)[1]} fill={catColor(k)} fillOpacity={1} stroke="none" radius={MARK.barR} ifOverflow="extendDomain" />
        ))}
        {intrinsic > 0 && <ReferenceLine className="ci-pv-intr" y={intrinsic} stroke="var(--tx-ink)" strokeDasharray="5 4" strokeWidth={1.2} />}
        {price > 0 && m > 0 && <ReferenceLine className="ci-pv-nowline" segment={[{ x: lineW, y: price }, { x: plotW, y: price }]} stroke="var(--tx-mute)" strokeWidth={1} />}
        {hasLine && <Line type="monotone" dataKey="p" stroke={BLUE} strokeWidth={MARK.line} dot={false} isAnimationActive={anim} />}
        {cur && <ReferenceLine segment={[{ x: cur.x, y: lo }, { x: cur.x, y: hi }]} {...CROSSHAIR} />}
        {last && <ReferenceDot className="ci-pv-end" x={last.x} y={last.p} {...ringDot(BLUE)} />}
        {cur && cur !== last && <ReferenceDot x={cur.x} y={cur.p} {...pickDot(BLUE)} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
  return (
    <div className="ci-pv" ref={boxRef}>
      {hasLine
        ? <ReadoutFrame id="price-value" label="1년 주가와 모형별 밸류에이션 밴드" headLabel="날짜" rows={rows} idx={idx} onKeyDown={onKeyDown}>{chart}</ReadoutFrame>
        : chart}
      <ul className="ci-pv-leg">
        {inRange.map((b, i) => (
          <li key={b.id}><i style={{ background: catColor(i) }} aria-hidden /><span data-server>{b.label}</span> <b>{won(b.lo)}~{won(b.hi)}</b></li>
        ))}
      </ul>
      <p className="ci-pv-key">
        {hasLine && <span><i className="ci-pv-sw line" aria-hidden />주가(1년)</span>}
        {price > 0 && m > 0 && <span className="ci-pv-now"><i className="ci-pv-sw now" aria-hidden />현재가 {won(price)}</span>}
        {intrinsic > 0 && <span><i className="ci-pv-sw dash" aria-hidden />내재가치 {won(intrinsic)}</span>}
      </p>
      {out.length > 0 && (
        <ul className="ci-pv-out" aria-label="그림 범위 밖 가치">
          {out.map((b) => <li key={b.id}><span data-server>{b.label}</span> {won(b.lo)}~{won(b.hi)}: 현재가와 너무 멀어 그림 밖에 적었습니다(원천 자료를 확인하십시오)</li>)}
        </ul>
      )}
    </div>
  );
}

/** 기간별 막대 — ★중립 한 색★(BU6b: 옛 화면은 마지막 해만 파랑이었는데 뜻이 없었다). 값이 없는 기간(null)은 막대가 비고 0 을 그리지 않는다.
 *  값은 읽는 줄에(`label` = 무엇의 막대인가). 표 쌍둥이는 달지 않는다 — 이 막대는 같은 값을 다 적은 재무 표 바로 아래에 있다(MoneySection). */
export function KpiBars({ data, dataKey, xKey = "year", height = 130, fmt = eok, label = "값" }: {
  data: ReadonlyArray<object>; dataKey: string; xKey?: string; color?: string; height?: number; fmt?: (n: number) => string; label?: string;
}) {
  const anim = useChartAnimation();
  const recs = data as ReadonlyArray<Record<string, unknown>>;
  const rows: ReadRow[] = recs.map((r) => {
    const v = r[dataKey];
    return { head: periodKo(String(r[xKey] ?? "")), cells: [{ key: dataKey, label, text: typeof v === "number" && Number.isFinite(v) ? fmt(v) : "N/A" }] };
  });
  const { idx, setIdx, onKeyDown } = useReadout(rows.length);
  const curX = idx >= 0 ? (recs[idx][xKey] as string | number) : null;
  return (
    <ReadoutFrame id={`kpi-${dataKey}`} label={`기간별 ${label}`} headLabel="기간" rows={rows} idx={idx} onKeyDown={onKeyDown} table={false}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data as unknown[]} margin={{ top: 14, right: 4, bottom: 0, left: 4 }} onMouseMove={followChart(setIdx)}>
          <XAxis dataKey={xKey} tick={AXIS} tickFormatter={periodShort} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
          {curX !== null && <ReferenceArea x1={curX} x2={curX} fill="var(--tx-soft)" fillOpacity={1} stroke="none" />}
          <ReferenceLine y={0} stroke="var(--tx-mute)" />
          <Bar isAnimationActive={anim} dataKey={dataKey} radius={BAR_TOP} maxBarSize={MARK.barMax} fill={BLUE} />
        </BarChart>
      </ResponsiveContainer>
    </ReadoutFrame>
  );
}

/** 이야기 그림 — 위 칸 매출(막대), 아래 칸 이익률(영업 = 실선+점 · 순 = 점선). ★이중 축이 아니다★: 단위가 다른 두 측정을 한 그림의 두 축에 올리면
 *  눈금 비율이 없는 관계를 만든다. 두 칸은 같은 왼쪽 축 폭을 쓰고, 아래 칸은 잰 폭으로 양 끝을 반 칸씩 띄워 ★막대 가운데 = 점 = 기간 글자★가 한 줄에 선다.
 *  (아래 칸에 `scale="band"` 를 쓰면 점은 띠 가운데로 가지만 기간 글자는 띠 왼쪽 끝에 남는다 — recharts 는 막대가 있는 그림에서만 글자를 가운데 둔다.) */
const ST_YW = 52;
const ST_MARGIN = { top: 10, right: 6, bottom: 8, left: 0 } as const;
export function StoryChart({ rows }: { rows: Row[] }) {
  const anim = useChartAnimation();
  const data = useMemo(() => rows.map((r) => ({ k: periodShort(r.k), revenue: r.revenue, opM: r.opMargin, niM: margin(r.ni, r.revenue) })), [rows]);
  const tickEok = (v: number) => (v === 0 ? "0" : Math.abs(v) >= 10000 ? `${Math.round(v / 10000).toLocaleString("ko-KR")}조` : `${Math.round(v).toLocaleString("ko-KR")}억`);
  const read: ReadRow[] = rows.map((r) => ({ head: periodKo(r.k), cells: [
    { key: "revenue", label: "매출", text: eokWon(r.revenue), color: BLUE },
    { key: "opM", label: "영업이익률", text: pctTxt(r.opMargin), color: catColor(1) },
    { key: "niM", label: "순이익률", text: pctTxt(margin(r.ni, r.revenue)), color: catColor(6) },
  ] }));
  const { idx, setIdx, onKeyDown } = useReadout(read.length);
  const curK = idx >= 0 ? data[idx].k : null;
  const figRef = useRef<HTMLElement>(null);
  const half = Math.max(0, useMeasuredWidth(figRef, 640) - ST_YW - ST_MARGIN.right - ST_MARGIN.left) / Math.max(1, data.length) / 2;   // 반 칸(px)
  return (
    <figure ref={figRef} className="ci-story" aria-label={`기간별 매출과 이익률: ${rows.map((r) => `${periodKo(r.k)} 매출 ${eokWon(r.revenue)}, 영업이익률 ${pctTxt(r.opMargin)}`).join(", ")}`}>
      <ReadoutFrame id="story" label="기간별 매출과 이익률" headLabel="기간" rows={read} idx={idx} onKeyDown={onKeyDown}>
        <div className="ci-story-panel" data-panel="revenue">
          <p className="ci-story-pt">매출</p>
          <ResponsiveContainer width="100%" height={150}>
            <ComposedChart data={data} margin={ST_MARGIN} onMouseMove={followChart(setIdx)}>
              <XAxis dataKey="k" scale="band" tick={false} tickLine={false} height={1} axisLine={{ stroke: "var(--tx-line)" }} />
              <YAxis tick={AXIS} tickFormatter={tickEok} width={ST_YW} tickLine={false} axisLine={false} />
              {curK !== null && <ReferenceArea x1={curK} x2={curK} fill="var(--tx-soft)" fillOpacity={1} stroke="none" />}
              <Bar dataKey="revenue" fill={BLUE} radius={BAR_TOP} maxBarSize={MARK.barMax} isAnimationActive={anim} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="ci-story-panel" data-panel="margin">
          <p className="ci-story-pt">이익률</p>
          <ResponsiveContainer width="100%" height={130}>
            <ComposedChart data={data} margin={ST_MARGIN} onMouseMove={followChart(setIdx)}>
              <XAxis dataKey="k" padding={{ left: half, right: half }} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--tx-line)" }} />
              <YAxis tick={AXIS} tickFormatter={(v: number) => `${v}%`} width={ST_YW} tickLine={false} axisLine={false} />
              <ReferenceLine y={0} stroke="var(--tx-line)" />
              {curK !== null && <ReferenceLine x={curK} {...CROSSHAIR} />}
              <Line dataKey="niM" stroke={catColor(6)} strokeWidth={MARK.quiet} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={anim} />
              <Line dataKey="opM" stroke={catColor(1)} strokeWidth={MARK.line} dot={ringDot(catColor(1))} connectNulls={false} isAnimationActive={anim} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </ReadoutFrame>
      <figcaption className="ci-story-cap">
        <span className="ci-story-key"><i className="sw bar" aria-hidden />매출(막대)</span>
        <span className="ci-story-key"><i className="sw op" aria-hidden />영업이익률(선)</span>
        <span className="ci-story-key"><i className="sw ni" aria-hidden />순이익률(점선)</span>
      </figcaption>
    </figure>
  );
}
