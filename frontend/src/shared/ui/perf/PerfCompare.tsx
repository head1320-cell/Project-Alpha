"use client";
/**
 * 둘 겹쳐 보기 — 두 자산 곡선 + 차이 띠 + 증거 띠 + 읽는 줄 (2026-11-09 · 성과 그림 문법 ③ §3.2)
 * ==========================================================================
 * ★서버가 맞춘 대로★ x·A·B·차이는 `POST /api/v1/perf/compare`(또는 캔버스 비교 노드 뷰)가 준 그대로 — 화면은 서식만 한다.
 * 날짜가 아니라 순번으로 맞춘 사실, 한쪽에 없는 날, 연습용 데이터는 띠와 글이 말한다(색·빗금만으로 말하지 않는다).
 * 툴팁 0 · 움직임 0 · 직접 SVG — PerfCurve 와 같은 기하 도우미(`perfGeo`). A = 잉크 · B = 범주색 1 · 차이 = 등락 두 팔.
 */
import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { cumPct, fmtSignedPct, fmtSignedPp, fmtValue, tickFormatter, type PerfCompareView, type PerfPoint } from "./perfView";
import { useMeasuredWidth } from "./useMeasuredWidth";
import { L_MIN, R_MIN, STRIP_H, TOP, XLAB_H, areaPath, argExt, linePath, pickIndexes, textW } from "./perfGeo";

export type CompareFocus = "a" | "b" | "both";
/** 위 패널 아래 눈금("×0.87")과 차이 패널 위 눈금("+6%p")이 부딪히지 않게 — PerfCurve 의 GAP(8)보다 넓다(검수에서 겹쳤다). */
const PANEL_GAP = 20;

const lastOf = (vals: PerfPoint[]): number | null => { for (let i = vals.length - 1; i >= 0; i--) { const v = vals[i]; if (v !== null) return v; } return null; };
const firstOf = (vals: PerfPoint[]): number | null => vals.find((v) => v !== null) ?? null;

export function PerfCompare({ view, height = 260, focus = "both", title = "두 자산 곡선과 차이" }:
  { view: PerfCompareView; height?: number; focus?: CompareFocus; title?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(wrap);
  const pid = useId();
  const n = view.x.length;
  const [idx, setIdx] = useState<number | null>(null);        // null = 마지막 날
  const cur = Math.min(n - 1, Math.max(0, idx ?? n - 1));
  const va = view.a.values;
  const vb = view.b.values;
  const vd = view.diffPp;

  const geo = useMemo(() => {
    const plotH = Math.max(90, height - TOP - STRIP_H - XLAB_H - PANEL_GAP);
    const eqH = Math.round(plotH * 0.68);
    const dfH = plotH - eqH;
    const base = view.base;
    const all = [...va, ...vb].filter((v): v is number => v !== null);
    let lo = Math.min(...all, base);
    let hi = Math.max(...all, base);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = base || 1; }
    if (hi - lo < 1e-9) hi = lo + (Math.abs(lo) || 1) * 0.1;
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    const tickFmt = tickFormatter(view.unit, hi, lo);
    const dAll = vd.filter((v): v is number => v !== null);
    let dlo = Math.min(0, ...dAll);
    let dhi = Math.max(0, ...dAll);
    if (dhi - dlo < 1e-9) dhi = dlo + 1;
    const dpad = (dhi - dlo) * 0.08;
    dlo -= dpad; dhi += dpad;
    const tickTexts = [tickFmt(hi), tickFmt(lo), tickFmt(base), fmtSignedPp(dhi, 0), fmtSignedPp(dlo, 0)];
    const L = Math.max(L_MIN, Math.ceil(Math.max(0, ...tickTexts.map(textW))) + 10);
    const lastA = lastOf(va);
    const lastB = lastOf(vb);
    const endTexts = [lastA, lastB].filter((v): v is number => v !== null).map((v) => fmtValue(view.unit, v));
    const R = Math.max(R_MIN, Math.ceil(Math.max(0, ...endTexts.map(textW))) + 10);
    const plotW = Math.max(40, width - L - R);
    const x = (i: number) => (n <= 1 ? L + plotW / 2 : L + (i / (n - 1)) * plotW);
    const yEq = (v: number) => TOP + (1 - (v - lo) / (hi - lo)) * eqH;
    const dfTop = TOP + eqH + PANEL_GAP;
    const yDf = (v: number) => dfTop + (1 - (v - dlo) / (dhi - dlo)) * dfH;
    const stripY = dfTop + dfH + 4;
    const maxPts = Math.max(24, Math.floor(plotW / 2));
    const must = [0, n - 1, argExt(va, "max"), argExt(va, "min"), argExt(vb, "max"), argExt(vb, "min"), argExt(vd, "max"), argExt(vd, "min")];
    const idxs = pickIndexes(n, maxPts, must);
    return { eqH, dfH, dfTop, L, plotW, x, yEq, yDf, hi, lo, dhi, dlo, tickFmt, stripY, idxs, lastA, lastB, base };
  }, [view.unit, view.base, va, vb, vd, width, height, n]);

  if (n < 2) {
    return <p className="pg-note pf-empty">겹쳐 그릴 곡선이 없어요 — 서버가 맞춘 날짜·값을 주지 않았어요.</p>;
  }

  const { x, yEq, yDf, L, plotW, idxs, stripY, lastA, lastB, base } = geo;
  const curA = va[cur] ?? null;
  const curB = vb[cur] ?? null;
  const curD = vd[cur] ?? null;
  const cumA = cumPct(firstOf(va), curA);
  const cumB = cumPct(firstOf(vb), curB);

  const move = (i: number) => setIdx(Math.min(n - 1, Math.max(0, i)));
  const onPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    move(Math.round(((e.clientX - rect.left - L) / Math.max(1, plotW)) * (n - 1)));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); move(cur - step); }
    else if (e.key === "ArrowRight") { e.preventDefault(); move(cur + step); }
    else if (e.key === "Home") { e.preventDefault(); move(0); }
    else if (e.key === "End") { e.preventDefault(); setIdx(null); }
  };

  // 오른쪽 끝 값 라벨 — 둘이 겹치면 B 를 밀고 안내선을 긋는다.
  const endAY = lastA === null ? null : yEq(lastA);
  let endBY = lastB === null ? null : yEq(lastB);
  const collide = endAY !== null && endBY !== null && Math.abs(endAY - endBY) < 13;
  if (collide && endBY !== null && endAY !== null) endBY = endAY + (endBY >= endAY ? 13 : -13);

  // 세로축 눈금 — 위·기준선·아래(기준선이 끝과 가까우면 둘) · 차이 패널은 위·0·아래.
  const ticks: { v: number; label: string; base?: boolean }[] = [{ v: geo.hi, label: geo.tickFmt(geo.hi) }];
  if (Math.abs(yEq(base) - yEq(geo.hi)) > 12 && Math.abs(yEq(base) - yEq(geo.lo)) > 12) ticks.push({ v: base, label: geo.tickFmt(base), base: true });
  ticks.push({ v: geo.lo, label: geo.tickFmt(geo.lo) });
  const upVals = vd.map((v) => (v === null ? null : Math.max(0, v)));
  const downVals = vd.map((v) => (v === null ? null : Math.min(0, v)));

  // 가로 라벨 — 셋이 들어갈 폭이 없으면 둘(처음·끝).
  const labW = textW(view.x[0].slice(0, 10));
  const xLabelIdx = Array.from(new Set(plotW >= labW * 3 + 16 ? [0, Math.floor((n - 1) / 2), n - 1] : [0, n - 1]));
  const xLabels = xLabelIdx.map((i) => ({ i, text: view.x[i].slice(0, 10) }));
  const stripBottom = stripY + STRIP_H - 4;
  const unitText = view.unit === "x" ? " (처음을 1로)" : view.unit === "base100" ? " (처음을 100으로)" : "";
  const ariaLabel = `${title} — ${view.a.label} ${fmtValue(view.unit, lastA)}, ${view.b.label} ${fmtValue(view.unit, lastB)}, 차이 ${fmtSignedPp(lastOf(vd))}. 화살표로 날짜를 옮겨 읽어요.`;

  return (
    <div className={`pg-chart pf-fig pf-cmp pf-cmp--focus-${focus}`} ref={wrap} data-alignment={view.alignment}>
      <svg className="pf-curve pf-cmp-svg" width={width} height={height} role="group" aria-label={ariaLabel} tabIndex={0}
           onPointerMove={onPointer} onPointerDown={onPointer} onKeyDown={onKey} onBlur={() => setIdx(null)}>
        <defs>
          <pattern id={`${pid}-hatch`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="pf-hatch-line" />
          </pattern>
        </defs>
        {/* 격자·세로축 */}
        {ticks.map((t) => (
          <g key={`t${t.v}`}>
            <line x1={L} x2={L + plotW} y1={yEq(t.v)} y2={yEq(t.v)} className={t.base ? "pf-baseline" : "pf-grid"} />
            <text x={L - 6} y={yEq(t.v) + 3.5} textAnchor="end" className="pf-ytick">{t.label}</text>
          </g>
        ))}
        {/* 두 곡선 — A 잉크 · B 범주색 */}
        <path d={linePath(idxs, vb, x, yEq)} className="pf-line-b" />
        <path d={linePath(idxs, va, x, yEq)} className="pf-line-a" />
        {/* 오른쪽 끝 값 */}
        {endAY !== null && <text x={L + plotW + 6} y={endAY + 4} className="pf-endlabel pf-endlabel--a">{fmtValue(view.unit, lastA)}</text>}
        {endBY !== null && (
          <g>
            {collide && lastB !== null && <line x1={L + plotW + 2} x2={L + plotW + 6} y1={yEq(lastB)} y2={endBY} className="pf-leader" />}
            <text x={L + plotW + 6} y={endBY + 4} className="pf-endlabel pf-endlabel--b">{fmtValue(view.unit, lastB)}</text>
          </g>
        )}
        {/* 차이 띠 — 0 기준 · 오름(빨강) 내림(파랑) 두 팔 · 선은 잉크 */}
        <g className="pf-diff">
          <line x1={L} x2={L + plotW} y1={yDf(0)} y2={yDf(0)} className="pf-baseline" />
          <path d={areaPath(idxs, upVals, x, yDf, yDf(0))} className="pf-diff-area pf-diff-area--up" />
          <path d={areaPath(idxs, downVals, x, yDf, yDf(0))} className="pf-diff-area pf-diff-area--down" />
          <path d={linePath(idxs, vd, x, yDf)} className="pf-diff-line" />
          {/* 차이가 0 이거나 한쪽으로만 벌어지면 끝 눈금이 0 눈금 위에 겹친다("−0%p") — 11px 안이면 끝 눈금을 생략(캔버스 검수 2026-11-09) */}
          {yDf(0) - geo.dfTop > 11 && <text x={L - 6} y={geo.dfTop + 4} textAnchor="end" className="pf-ytick">{fmtSignedPp(geo.dhi, 0)}</text>}
          <text x={L - 6} y={yDf(0) + 3.5} textAnchor="end" className="pf-ytick">0</text>
          {geo.dfTop + geo.dfH - yDf(0) > 11 && <text x={L - 6} y={geo.dfTop + geo.dfH} textAnchor="end" className="pf-ytick">{fmtSignedPp(geo.dlo, 0)}</text>}
        </g>
        {/* 십자선·점 */}
        <g className="pf-cross">
          <line x1={x(cur)} x2={x(cur)} y1={TOP} y2={stripY - 2} className="pf-crossline" />
          {curA !== null && <circle cx={x(cur)} cy={yEq(curA)} r={4} className="pf-dot pf-dot--a" />}
          {curB !== null && <circle cx={x(cur)} cy={yEq(curB)} r={4} className="pf-dot pf-dot--b" />}
          {curD !== null && <circle cx={x(cur)} cy={yDf(curD)} r={3.5} className="pf-dot pf-dot--diff" />}
        </g>
        {/* 증거 띠 — 순번으로 맞췄으면 점선 테두리 · 한쪽이라도 연습용이면 빗금 */}
        <g className="pf-strip" transform={`translate(0 ${stripY})`}>
          <rect x={L} y={3} width={plotW} height={STRIP_H - 10} className="pf-strip-sim" />
          {view.alignment === "index" && <rect x={L} y={0.5} width={plotW} height={STRIP_H - 5} className="pf-strip-index" />}
          {view.practice === true && <rect x={L} y={0} width={plotW} height={STRIP_H - 4} fill={`url(#${pid}-hatch)`} className="pf-strip-practice" />}
        </g>
        {/* 가로축 글자 */}
        {xLabels.map((l, k) => (
          <text key={l.i} x={x(l.i)} y={stripBottom + XLAB_H - 2} className="pf-xtick"
                textAnchor={k === 0 ? "start" : k === xLabels.length - 1 ? "end" : "middle"}>{l.text}</text>
        ))}
      </svg>
      {/* 읽는 줄 — 늘 보인다 · 포인터·키보드가 옮긴다 */}
      <p className="pf-read" aria-live="polite">
        <b className="pf-read-date">{view.x[cur].slice(0, 10)}</b>
        <span className="pf-read-item"><i className="pf-key pf-key--a" aria-hidden="true" />{view.a.label} <b>{fmtValue(view.unit, curA)}</b>
          {cumA !== null && <span className={`pf-delta pf-delta--${cumA >= 0 ? "up" : "down"}`}>({fmtSignedPct(cumA)})</span>}</span>
        <span className="pf-read-item"><i className="pf-key pf-key--b" aria-hidden="true" />{view.b.label} <b>{fmtValue(view.unit, curB)}</b>
          {cumB !== null && <span className={`pf-delta pf-delta--${cumB >= 0 ? "up" : "down"}`}>({fmtSignedPct(cumB)})</span>}</span>
        <span className="pf-read-item pf-read-diff"><i className="pf-key pf-key--diff" aria-hidden="true" />차이 <b>{fmtSignedPp(curD)}</b></span>
      </p>
      {/* 범례 — 두 계열 + 차이의 뜻 */}
      <p className="pf-legend">
        <span><i className="pf-key pf-key--a" aria-hidden="true" />{view.a.label}{unitText}</span>
        <span><i className="pf-key pf-key--b" aria-hidden="true" />{view.b.label}</span>
        <span><i className="pf-key pf-key--diff" aria-hidden="true" />차이 = {view.b.label} − {view.a.label} (%p)</span>
      </p>
      {/* 띠 범례 — 글자가 띠의 뜻을 말한다 */}
      <p className="pf-strip-legend">
        {view.alignment === "index" && view.note && <span className="pf-strip-legend-align"><i className="pf-skey pf-skey--index" aria-hidden="true" />{view.note}</span>}
        {view.alignment === "date" && view.note && (
          <span className="pf-strip-legend-missing">{view.note}
            {view.missingA > 0 ? ` ${view.a.label}에 없는 날 ${view.missingA}일.` : ""}{view.missingB > 0 ? ` ${view.b.label}에 없는 날 ${view.missingB}일.` : ""}
          </span>
        )}
        {view.practice === true && <span className="pf-strip-legend-practice"><i className="pf-skey pf-skey--practice" aria-hidden="true" />연습용 데이터</span>}
        {view.practice === null && <span className="pf-strip-legend-unknown">데이터가 실제인지 몰라요</span>}
      </p>
      {/* 표 쌍둥이 */}
      <details className="pf-table pf-cmp-table">
        <summary>표로 보기</summary>
        <div className="pf-table-scroll">
          <table className="pg-table pf-table-curve">
            <thead><tr><th>{view.alignment === "date" ? "날짜" : "순번"}</th><th className="pg-td-num">{view.a.label}</th><th className="pg-td-num">{view.b.label}</th><th className="pg-td-num">차이</th></tr></thead>
            <tbody>
              {view.x.map((d, i) => (
                <tr key={d}>
                  <td>{d.slice(0, 10)}</td>
                  <td className="pg-td-num">{fmtValue(view.unit, va[i] ?? null)}</td>
                  <td className="pg-td-num">{fmtValue(view.unit, vb[i] ?? null)}</td>
                  <td className="pg-td-num">{fmtSignedPp(vd[i] ?? null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
