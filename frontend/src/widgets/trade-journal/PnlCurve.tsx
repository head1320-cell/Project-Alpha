"use client";
/**
 * 누적 실현손익과 고점 대비 하락 — 그림 하나 + 읽는 줄 (성과 그림 문법 `shared/ui/perf` 의 표식·역할 변수 그대로)
 * ==========================================================================
 * `PerfCurve` 를 쓰지 않는 까닭: 그 부품은 자산 곡선(시작값 1·100 · 낙폭 %)을 그린다. 여기는 ★0 에서 시작하는 원 단위 손익★이고
 * 하락도 원이다(계좌 평가금액을 모르므로 %를 만들지 않는다). 기하 도우미(`perfGeo`)와 표식 클래스(`pf-*`)만 같이 쓴다.
 * 가로축은 거래 순서다(청산 순) — 장중 거래와 며칠 건너뛴 거래가 한 그림에서 같은 간격으로 읽힌다. 날짜는 읽는 줄이 말한다.
 * 툴팁 0 — 값은 그림 아래 읽는 줄에 늘 보이고, 포인터·키보드(←→ Home End)로 거래를 옮긴다.
 */
import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { CurvePoint, PnlBasis, TradeRow } from "@/entities/trade-journal";
import { krAxisTick } from "@/shared/lib/krFormat";
import { GAP, L_MIN, TOP, XLAB_H, areaPath, linePath, pickIndexes, textW } from "@/shared/ui/perf/perfGeo";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";
import { amountWon, signedWon, sign, whenText } from "./format";

const R = 14;                     // 오른쪽 여백(끝 점이 잘리지 않게)
const BASIS_KO: Record<PnlBasis, string> = { net: "비용 후", gross: "비용 전" };

export function PnlCurve({ points, trades, basis, maxDrawdown, maxDrawdownAt, height = 250 }: {
  points: CurvePoint[]; trades: TradeRow[]; basis: PnlBasis; maxDrawdown: number | null; maxDrawdownAt: string | null; height?: number;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(wrap);
  const n = points.length;                                     // 거래 수 — 그림의 점은 출발선(0)을 더해 n + 1
  const [pick, setPick] = useState<number | null>(null);        // null = 마지막 거래
  const cur = Math.min(n, Math.max(0, pick ?? n));

  const geo = useMemo(() => {
    const cum = [0, ...points.map((p) => p.cum)];
    const dd = [0, ...points.map((p) => -p.drawdown)];
    const hasDd = points.some((p) => p.drawdown > 0);
    const plotH = Math.max(90, height - TOP - XLAB_H - (hasDd ? GAP : 0));
    const eqH = hasDd ? Math.round(plotH * 0.7) : plotH;
    const ddH = plotH - eqH;
    let lo = Math.min(...cum), hi = Math.max(...cum);
    if (hi - lo < 1e-9) hi = lo + 1;
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    const ddMin = Math.min(...dd);
    const tick = krAxisTick(Math.max(Math.abs(hi), Math.abs(lo), Math.abs(ddMin)));
    const labels = [tick(hi), tick(lo), "0", ...(hasDd ? [tick(ddMin)] : [])];
    const L = Math.max(L_MIN, Math.ceil(Math.max(...labels.map(textW))) + 10);
    const plotW = Math.max(40, width - L - R);
    const x = (i: number) => (n === 0 ? L : L + (i / n) * plotW);
    const yEq = (v: number) => TOP + (1 - (v - lo) / (hi - lo)) * eqH;
    const ddTop = TOP + eqH + GAP;
    const yDd = (v: number) => ddTop + (ddMin < 0 ? (v / ddMin) * ddH : 0);
    const worst = dd.indexOf(ddMin);
    const idx = pickIndexes(n + 1, Math.max(24, Math.floor(plotW / 2)), [0, n, cum.indexOf(Math.max(...cum)), cum.indexOf(Math.min(...cum)), worst]);
    return { cum, dd, hasDd, eqH, ddH, lo, hi, ddMin, tick, L, plotW, x, yEq, ddTop, yDd, idx, worst };
  }, [points, width, height, n]);

  if (n === 0) return null;
  const { cum, dd, hasDd, lo, hi, ddMin, tick, L, plotW, x, yEq, ddTop, yDd, idx, worst } = geo;
  const move = (i: number) => setPick(Math.min(n, Math.max(0, i)));
  const onPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    move(Math.round(((e.clientX - rect.left - L) / Math.max(1, plotW)) * n));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); move(cur - step); }
    else if (e.key === "ArrowRight") { e.preventDefault(); move(cur + step); }
    else if (e.key === "Home") { e.preventDefault(); move(1); }
    else if (e.key === "End") { e.preventDefault(); setPick(null); }
  };

  const point = cur > 0 ? points[cur - 1] : null;
  const trade = cur > 0 ? trades[cur - 1] ?? null : null;
  const last = points[n - 1];
  const zeroApart = Math.abs(yEq(0) - yEq(hi)) > 12 && Math.abs(yEq(0) - yEq(lo)) > 12;
  const first = points[0].at.slice(0, 10), end = last.at.slice(0, 10);
  const aria = `누적 실현손익(${BASIS_KO[basis]})과 고점 대비 하락. 거래 ${n}건, 마지막 누적 ${signedWon(last.cum)}. 화살표 키로 거래를 이동해 값을 읽습니다.`;

  return (
    <div className="pf-fig tj-curve-fig" ref={wrap}>
      <svg className="pf-curve tj-curve" width={width} height={height} role="group" aria-label={aria} tabIndex={0}
           onPointerMove={onPointer} onPointerDown={onPointer} onKeyDown={onKey} onBlur={() => setPick(null)}>
        {/* 격자·세로축 — 위·0·아래 */}
        <line x1={L} x2={L + plotW} y1={yEq(hi)} y2={yEq(hi)} className="pf-grid" />
        <text x={L - 6} y={yEq(hi) + 3.5} textAnchor="end" className="pf-ytick">{tick(hi)}</text>
        <line x1={L} x2={L + plotW} y1={yEq(lo)} y2={yEq(lo)} className="pf-grid" />
        <text x={L - 6} y={yEq(lo) + 3.5} textAnchor="end" className="pf-ytick">{tick(lo)}</text>
        <line x1={L} x2={L + plotW} y1={yEq(0)} y2={yEq(0)} className="pf-baseline" />
        {zeroApart && <text x={L - 6} y={yEq(0) + 3.5} textAnchor="end" className="pf-ytick">0</text>}
        {/* 고점 대비 하락(물속) */}
        {hasDd && (
          <g className="pf-dd">
            <line x1={L} x2={L + plotW} y1={ddTop} y2={ddTop} className="pf-baseline" />
            <path d={areaPath(idx, dd, x, yDd, ddTop)} className="pf-dd-area" />
            <path d={linePath(idx, dd, x, yDd)} className="pf-dd-line" />
            <text x={L - 6} y={yDd(ddMin) + 3.5} textAnchor="end" className="pf-ytick">{tick(ddMin)}</text>
          </g>
        )}
        {/* 누적 실현손익 */}
        <path d={linePath(idx, cum, x, yEq)} className="pf-line-port" />
        {/* 십자선·점 */}
        <g className="pf-cross">
          <line x1={x(cur)} x2={x(cur)} y1={TOP} y2={height - XLAB_H} className="pf-crossline" />
          <circle cx={x(cur)} cy={yEq(cum[cur])} r={4} className="pf-dot pf-dot--port" />
          {hasDd && <circle cx={x(cur)} cy={yDd(dd[cur])} r={3.5} className="pf-dot pf-dot--dd" />}
        </g>
        {/* 가로축 — 처음과 마지막 청산일 */}
        <text x={L} y={height - 3} className="pf-xtick" textAnchor="start">{first}</text>
        {end !== first || plotW > textW(first) * 2 + 16 ? <text x={L + plotW} y={height - 3} className="pf-xtick" textAnchor="end">{end}</text> : null}
      </svg>
      {/* 읽는 줄 — 늘 보인다 */}
      <p className="pf-read tj-curve-read" aria-live="polite">
        {point ? (
          <>
            <b className="pf-read-date">{cur}번째 거래</b>
            <span className="pf-read-item">{whenText(point.at, trade ? trade.has_time : true)}</span>
            {trade ? <span className="pf-read-item">{trade.name ?? trade.symbol}</span> : null}
            <span className="pf-read-item">이 거래 <b className={`pf-delta--${sign(point.pnl)}`}>{signedWon(point.pnl)}</b></span>
            <span className="pf-read-item"><i className="pf-key pf-key--port" aria-hidden="true" />누적 <b className={`pf-delta--${sign(point.cum)}`}>{signedWon(point.cum)}</b></span>
            <span className="pf-read-item"><i className="pf-key pf-key--dd" aria-hidden="true" />고점 대비 하락 <b>{amountWon(point.drawdown)}</b></span>
          </>
        ) : (
          <><b className="pf-read-date">출발선</b><span className="pf-read-item">누적 <b>0원</b></span></>
        )}
      </p>
      <p className="pf-legend">
        <span className="tj-curve-basis"><i className="pf-key pf-key--port" aria-hidden="true" />누적 실현손익({BASIS_KO[basis]}) · 가로축은 청산 순서</span>
        {hasDd && maxDrawdown !== null ? (
          <span className="tj-curve-max"><i className="pf-key pf-key--dd" aria-hidden="true" />고점 대비 하락의 최댓값 {amountWon(maxDrawdown)}
            {maxDrawdownAt ? ` (${worst}번째 거래 · ${whenText(maxDrawdownAt)})` : ""}</span>
        ) : <span className="tj-curve-max pf-legend-none">고점 대비 하락 없음</span>}
      </p>
    </div>
  );
}
