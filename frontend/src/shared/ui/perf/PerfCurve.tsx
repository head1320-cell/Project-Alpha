"use client";
/**
 * 그림 하나 — 자산 곡선 + 낙폭(물속) + 증거 띠 + 읽는 줄 (2026-11-09 · 캔버스 성과 그림 문법 §4.2)
 * ==========================================================================
 * ★그림이 모르는 것을 그림 안에 적는다★ 시간축 밑의 증거 띠가 배움 구간·리밸런싱 날·기준일·합성 데이터를 말하고, 범례가 벤치마크
 * 없음을 말한다. ★툴팁 0★ — 값은 그림 아래 '읽는 줄' 에 늘 보이고, 포인터·키보드(←→ Home End)로 날짜를 옮긴다(ADR-003 §2.4).
 * 직접 그린 SVG(recharts 아님) · 폭은 px 로 잰다 · 움직임 없음. 색은 역할 변수(`--pf-*`)만 — 포트폴리오 = 잉크 · 벤치마크 = 회색 ·
 * 낙폭 = 등락 '내림' 색(파랑) · 파랑 행동색은 데이터에 쓰지 않는다. 솎을 때 양 끝·최고점·낙폭 바닥은 반드시 남긴다.
 */
import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { cumPct, fmtPct, fmtSignedPct, fmtValue, type PerfPoint, type PerfView } from "./perfView";
import { krAxisTick } from "@/shared/lib/krFormat";
import { useMeasuredWidth } from "./useMeasuredWidth";

const L_MIN = 46;      // 세로축 글자 자리(최소 — 라벨이 길면 넓힌다 · 원 단위 "9,983만원")
const R_MIN = 58;      // 오른쪽 끝 값 라벨 자리(최소)
const TOP = 10;
/** 글자 폭 어림(11px 글꼴) — 한글 11px · 쉼표·점 3.5px · 그 밖 6.3px. 자리를 라벨에 맞추려고 잰다(잘리지 않게). */
const textW = (s: string) => [...s].reduce((w, ch) => w + (/[가-힣]/.test(ch) ? 11 : /[,.]/.test(ch) ? 3.5 : 6.3), 0);
const STRIP_H = 14;
const XLAB_H = 16;
const GAP = 8;

const day = (s: string) => Date.parse(s.slice(0, 10));
const days = (a: string, b: string) => Math.max(0, Math.round((day(b) - day(a)) / 86_400_000));

/** 솎기 — 폭에 맞춰 고르게, ★양 끝·최고점·최저점·낙폭 바닥★은 반드시. */
function pickIndexes(n: number, maxPts: number, must: number[]): number[] {
  const set = new Set<number>();
  if (n <= maxPts) for (let i = 0; i < n; i++) set.add(i);
  else { const step = (n - 1) / (maxPts - 1); for (let i = 0; i < maxPts; i++) set.add(Math.round(i * step)); }
  for (const m of must) if (m >= 0 && m < n) set.add(m);
  return [...set].sort((a, b) => a - b);
}

function argExt(vals: PerfPoint[], pick: "max" | "min"): number {
  let best = -1;
  for (let i = 0; i < vals.length; i++) {
    const v = vals[i];
    if (v === null) continue;
    if (best < 0 || (pick === "max" ? v > (vals[best] as number) : v < (vals[best] as number))) best = i;
  }
  return best;
}

/** 선 경로 — 값이 null 인 날은 끊는다(0 으로 잇지 않는다). */
function linePath(idx: number[], vals: PerfPoint[], x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  for (const i of idx) {
    const v = vals[i];
    if (v === null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** 면 경로 — 이어진 구간마다 기준선으로 닫는다. */
function areaPath(idx: number[], vals: PerfPoint[], x: (i: number) => number, y: (v: number) => number, y0: number): string {
  let d = "";
  let run: number[] = [];
  const flush = () => {
    if (run.length) {
      d += `M${x(run[0]).toFixed(1)} ${y0.toFixed(1)}`;
      for (const i of run) d += `L${x(i).toFixed(1)} ${y(vals[i] as number).toFixed(1)}`;
      d += `L${x(run[run.length - 1]).toFixed(1)} ${y0.toFixed(1)}Z`;
    }
    run = [];
  };
  for (const i of idx) { if (vals[i] === null) flush(); else run.push(i); }
  flush();
  return d;
}

export function PerfCurve({ view, height = 230, title = "자산 곡선과 낙폭" }: { view: PerfView; height?: number; title?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(wrap);
  const pid = useId();
  const n = view.dates.length;
  const [idx, setIdx] = useState<number | null>(null);        // null = 마지막 날
  const cur = Math.min(n - 1, Math.max(0, idx ?? n - 1));

  const geo = useMemo(() => {
    const hasDd = !!view.drawdown && view.drawdown.some((v) => v !== null);
    const plotH = Math.max(80, height - TOP - STRIP_H - XLAB_H - (hasDd ? GAP : 0));
    const eqH = hasDd ? Math.round(plotH * 0.7) : plotH;
    const ddH = hasDd ? plotH - eqH : 0;
    // 세로 눈금(값) — 폭과 무관. 자리(L·R)는 이 라벨들의 폭에 맞춘다.
    const all = [...view.equity, ...(view.bench ?? [])].filter((v): v is number => v !== null);
    const baseline = view.unit === "x" ? 1 : (view.equity.find((v) => v !== null) ?? null);
    let lo = Math.min(...all, ...(baseline === null ? [] : [baseline]));
    let hi = Math.max(...all, ...(baseline === null ? [] : [baseline]));
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 1; }
    if (hi - lo < 1e-9) { hi = lo + (Math.abs(lo) || 1) * 0.1; }
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    // 위·아래 눈금은 여백의 끝(= 곡선 최댓값 + 6% · 최솟값 − 6%) — 맨 위 눈금이 곡선 최댓값보다 작게 적히지 않게.
    const yTopV = hi, yBotV = lo;
    // 원 단위 눈금은 한 축 한 단위(만·억)로 짧게("1.05억" · "5,636만" · "112") — 끝값·읽는 줄은 그대로 "1.2억원".
    const tickFmt = view.unit === "krw" ? krAxisTick(Math.max(Math.abs(hi), Math.abs(lo))) : (v: number) => fmtValue("x", v);
    const ddMin = hasDd ? Math.min(0, ...(view.drawdown as PerfPoint[]).filter((v): v is number => v !== null)) : 0;
    const tickTexts = [tickFmt(yTopV), tickFmt(yBotV), ...(baseline === null ? [] : [tickFmt(baseline)]),
                       ...(hasDd ? [fmtPct(ddMin, 0)] : [])];
    const L = Math.max(L_MIN, Math.ceil(Math.max(0, ...tickTexts.map(textW))) + 10);
    const endTexts = [view.equity[n - 1] ?? null, view.bench ? (view.bench[n - 1] ?? null) : null].filter((v): v is number => v !== null)
      .map((v) => fmtValue(view.unit, v));
    const R = Math.max(R_MIN, Math.ceil(Math.max(0, ...endTexts.map(textW))) + 10);
    // 배움 구간 — 곡선 첫 날 앞의 수익률 자료 기간. 길이에 비례하되 폭의 1/4 까지만.
    const learnDays = view.learnFrom && n ? days(view.learnFrom, view.dates[0]) : 0;
    const simDays = n > 1 ? Math.max(1, days(view.dates[0], view.dates[n - 1])) : 1;
    const innerW = Math.max(40, width - L - R);
    const learnW = learnDays > 0 ? Math.round(Math.min(0.25, learnDays / (learnDays + simDays)) * innerW) : 0;
    const plotW = innerW - learnW;
    const x0 = L + learnW;
    const x = (i: number) => (n <= 1 ? x0 + plotW / 2 : x0 + (i / (n - 1)) * plotW);
    const yEq = (v: number) => TOP + (1 - (v - lo) / (hi - lo)) * eqH;
    const ddTop = TOP + eqH + GAP;
    const yDd = (v: number) => ddTop + (ddMin < 0 ? (v / ddMin) * ddH : 0);
    const stripY = TOP + eqH + (hasDd ? GAP + ddH : 0) + 4;
    const maxPts = Math.max(24, Math.floor(plotW / 2));
    const must = [0, n - 1, argExt(view.equity, "max"), argExt(view.equity, "min"), hasDd ? argExt(view.drawdown as PerfPoint[], "min") : -1];
    const idxs = pickIndexes(n, maxPts, must);
    return { hasDd, eqH, ddH, learnW, plotW, x0, x, yTopV, yBotV, baseline, yEq, ddTop, ddMin, yDd, stripY, idxs, learnDays, L, tickFmt };
  }, [view, width, height, n]);

  const dateIndex = useMemo(() => new Map(view.dates.map((d, i) => [d.slice(0, 10), i])), [view.dates]);
  const rebalIdx = useMemo(() => {
    const out: { i: number; turnover: number | null }[] = [];
    for (const r of view.rebalances) {
      const key = r.date.slice(0, 10);
      let i = dateIndex.get(key);
      if (i === undefined) { i = view.dates.findIndex((d) => d.slice(0, 10) >= key); }
      if (i !== undefined && i >= 0) out.push({ i, turnover: r.turnover_pct });
    }
    return out;
  }, [view.rebalances, view.dates, dateIndex]);
  const asOfIdx = useMemo(() => {
    if (!view.asOf || !n) return null;
    const key = view.asOf.slice(0, 10);
    const i = dateIndex.get(key);
    if (i !== undefined) return i;
    return key > view.dates[n - 1].slice(0, 10) ? n - 1 : view.dates.findIndex((d) => d.slice(0, 10) >= key);
  }, [view.asOf, view.dates, dateIndex, n]);

  if (n < 2) {
    return <p className="pg-note pf-empty">그릴 곡선이 없어요 — 서버가 날짜·값을 주지 않았어요.</p>;
  }

  const { x, yEq, yDd, hasDd, stripY, idxs, baseline, learnW, x0, plotW, learnDays, L } = geo;
  const first = view.equity.find((v) => v !== null) ?? null;
  const lastPort = view.equity[n - 1];
  const lastBench = view.bench ? view.bench[n - 1] : null;
  const curPort = view.equity[cur];
  const curBench = view.bench ? view.bench[cur] : null;
  const curDd = view.drawdown ? view.drawdown[cur] : null;
  const curRebal = rebalIdx.find((r) => r.i === cur);
  const cumCur = cumPct(first, curPort);

  const move = (i: number) => setIdx(Math.min(n - 1, Math.max(0, i)));
  const onPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left - x0;
    move(Math.round((px / Math.max(1, plotW)) * (n - 1)));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); move(cur - step); }
    else if (e.key === "ArrowRight") { e.preventDefault(); move(cur + step); }
    else if (e.key === "Home") { e.preventDefault(); move(0); }
    else if (e.key === "End") { e.preventDefault(); setIdx(null); }
  };

  // 오른쪽 끝 값 라벨 — 둘이 겹치면 벤치마크를 아래로 밀고 안내선을 긋는다.
  const endPortY = lastPort === null ? null : yEq(lastPort);
  let endBenchY = lastBench === null ? null : yEq(lastBench);
  const collide = endPortY !== null && endBenchY !== null && Math.abs(endPortY - endBenchY) < 13;
  if (collide && endBenchY !== null && endPortY !== null) endBenchY = endPortY + (endBenchY >= endPortY ? 13 : -13);

  // 세로축 눈금 — 위·아래·기준선 셋(겹치면 기준선만 둘).
  const ticks: { v: number; label: string; base?: boolean }[] = [];
  const tickLabel = geo.tickFmt;
  const { yTopV: yTop, yBotV: yBot } = geo;
  ticks.push({ v: yTop, label: tickLabel(yTop) });
  if (baseline !== null && Math.abs(yEq(baseline) - yEq(yTop)) > 12 && Math.abs(yEq(baseline) - yEq(yBot)) > 12) ticks.push({ v: baseline, label: tickLabel(baseline), base: true });
  ticks.push({ v: yBot, label: tickLabel(yBot) });

  // 날짜 라벨 — 셋(처음·가운데·끝)이 들어갈 폭이 없으면 둘(처음·끝). 좁은 화면(390px)에서 셋이 겹쳐 읽히지 않던 것을 고친다.
  const dateW = textW(view.dates[0].slice(0, 10));
  const xLabelIdx = Array.from(new Set(plotW >= dateW * 3 + 16 ? [0, Math.floor((n - 1) / 2), n - 1] : [0, n - 1]));
  const xLabels = xLabelIdx.map((i) => ({ i, text: view.dates[i].slice(0, 10) }));
  const stripBottom = stripY + STRIP_H - 4;
  const ariaLabel = `${title} — 포트폴리오 ${fmtValue(view.unit, lastPort)}${view.bench ? `, 벤치마크 ${fmtValue(view.unit, lastBench)}` : ""}. 화살표로 날짜를 옮겨 읽어요.`;
  // 띠 범례 — 리밸런싱 날짜가 없는 노드(불러오기·전략 묶음)는 횟수만 알거나 아예 모른다: 아는 만큼만 말한다.
  const nReb = view.cost.nRebalances;
  const rebalLegend = rebalIdx.length > 0 ? `리밸런싱 ${rebalIdx.length}번`
    : nReb === null ? null : nReb > 0 ? `리밸런싱 ${nReb}번 (날짜는 기록에 없어요)` : "리밸런싱 없음";

  return (
    <div className="pg-chart pf-fig" ref={wrap}>
      <svg className="pf-curve" width={width} height={height} role="group" aria-label={ariaLabel} tabIndex={0}
           onPointerMove={onPointer} onPointerDown={onPointer} onKeyDown={onKey} onBlur={() => setIdx(null)}>
        <defs>
          <pattern id={`${pid}-hatch`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="pf-hatch-line" />
          </pattern>
        </defs>
        {/* 격자·세로축 */}
        {ticks.map((t) => (
          <g key={`t${t.v}`}>
            <line x1={x0} x2={x0 + plotW} y1={yEq(t.v)} y2={yEq(t.v)} className={t.base ? "pf-baseline" : "pf-grid"} />
            <text x={L - 6} y={yEq(t.v) + 3.5} textAnchor="end" className="pf-ytick">{t.label}</text>
          </g>
        ))}
        {/* 배움 구간(곡선 앞) — 빗금만. 글자는 띠 범례가 맡는다(세로축 눈금 글자와 부딪히지 않게). */}
        {learnW > 0 && <rect x={L} y={TOP} width={learnW} height={geo.eqH} fill={`url(#${pid}-hatch)`} className="pf-learn pf-learn-fill" />}
        {/* 낙폭(물속) */}
        {hasDd && (
          <g className="pf-dd">
            <line x1={x0} x2={x0 + plotW} y1={geo.ddTop} y2={geo.ddTop} className="pf-baseline" />
            <path d={areaPath(idxs, view.drawdown as PerfPoint[], x, yDd, geo.ddTop)} className="pf-dd-area" />
            <path d={linePath(idxs, view.drawdown as PerfPoint[], x, yDd)} className="pf-dd-line" />
            <text x={L - 6} y={geo.ddTop + geo.ddH} textAnchor="end" className="pf-ytick">{fmtPct(geo.ddMin, 0)}</text>
          </g>
        )}
        {/* 벤치마크 → 포트폴리오(위에) */}
        {view.bench && <path d={linePath(idxs, view.bench, x, yEq)} className="pf-line-bench" />}
        <path d={linePath(idxs, view.equity, x, yEq)} className="pf-line-port" />
        {/* 오른쪽 끝 값 */}
        {endPortY !== null && <text x={x0 + plotW + 6} y={endPortY + 4} className="pf-endlabel pf-endlabel--port">{fmtValue(view.unit, lastPort)}</text>}
        {endBenchY !== null && (
          <g>
            {collide && endPortY !== null && <line x1={x0 + plotW + 2} x2={x0 + plotW + 6} y1={yEq(lastBench as number)} y2={endBenchY} className="pf-leader" />}
            <text x={x0 + plotW + 6} y={endBenchY + 4} className="pf-endlabel pf-endlabel--bench">{fmtValue(view.unit, lastBench)}</text>
          </g>
        )}
        {/* 십자선·점 */}
        <g className="pf-cross">
          <line x1={x(cur)} x2={x(cur)} y1={TOP} y2={stripY - 2} className="pf-crossline" />
          {curPort !== null && <circle cx={x(cur)} cy={yEq(curPort)} r={4} className="pf-dot pf-dot--port" />}
          {curBench !== null && curBench !== undefined && <circle cx={x(cur)} cy={yEq(curBench)} r={4} className="pf-dot pf-dot--bench" />}
          {hasDd && curDd !== null && curDd !== undefined && <circle cx={x(cur)} cy={yDd(curDd)} r={3.5} className="pf-dot pf-dot--dd" />}
        </g>
        {/* 증거 띠 */}
        <g className="pf-strip" transform={`translate(0 ${stripY})`}>
          {learnW > 0 && <rect x={L} y={0} width={learnW} height={STRIP_H - 4} fill={`url(#${pid}-hatch)`} className="pf-strip-learn" />}
          <rect x={x0} y={3} width={plotW} height={STRIP_H - 10} className="pf-strip-sim" />
          {view.practice === true && <rect x={L} y={0} width={learnW + plotW} height={STRIP_H - 4} fill={`url(#${pid}-hatch)`} className="pf-strip-practice" />}
          {rebalIdx.map((r, k) => <line key={k} x1={x(r.i)} x2={x(r.i)} y1={0} y2={STRIP_H - 4} className="pf-strip-rebal" />)}
          {asOfIdx !== null && asOfIdx >= 0 && (
            <path d={`M${(x(asOfIdx) - 4).toFixed(1)} ${STRIP_H - 4}L${x(asOfIdx).toFixed(1)} ${STRIP_H - 10}L${(x(asOfIdx) + 4).toFixed(1)} ${STRIP_H - 4}Z`} className="pf-strip-asof" />
          )}
        </g>
        {/* 가로축 글자 */}
        {xLabels.map((l, k) => (
          <text key={l.i} x={x(l.i)} y={stripBottom + XLAB_H - 2} className="pf-xtick"
                textAnchor={k === 0 ? "start" : k === xLabels.length - 1 ? "end" : "middle"}>{l.text}</text>
        ))}
      </svg>
      {/* 읽는 줄 — 늘 보인다 · 포인터·키보드가 옮긴다 */}
      <p className="pf-read" aria-live="polite">
        <b className="pf-read-date">{view.dates[cur].slice(0, 10)}</b>
        <span className="pf-read-item"><i className="pf-key pf-key--port" aria-hidden="true" />포트폴리오 <b>{fmtValue(view.unit, curPort)}</b>
          {cumCur !== null && <span className={`pf-delta pf-delta--${cumCur >= 0 ? "up" : "down"}`}>(첫날 대비 {fmtSignedPct(cumCur)})</span>}</span>
        {view.bench && <span className="pf-read-item"><i className="pf-key pf-key--bench" aria-hidden="true" />{view.benchLabel ?? "벤치마크"} <b>{fmtValue(view.unit, curBench ?? null)}</b></span>}
        {hasDd && <span className="pf-read-item"><i className="pf-key pf-key--dd" aria-hidden="true" />낙폭 <b>{fmtPct(curDd ?? null)}</b></span>}
        {curRebal && <span className="pf-read-item pf-read-rebal">이날 리밸런싱{curRebal.turnover !== null ? ` (회전율 ${fmtPct(curRebal.turnover, 0)})` : ""}</span>}
      </p>
      {/* 범례 — 두 계열이면 늘 · 벤치마크가 없으면 그렇게 말한다 */}
      <p className="pf-legend">
        <span><i className="pf-key pf-key--port" aria-hidden="true" />포트폴리오{view.unit === "x" ? " (처음을 1로)" : ""}</span>
        {view.bench
          ? <span><i className="pf-key pf-key--bench" aria-hidden="true" />벤치마크{view.benchLabel ? ` ${view.benchLabel}` : ""}</span>
          : <span className="pf-legend-none">벤치마크 없음 — 이 실행은 비교 지수를 쓰지 않았어요</span>}
        {hasDd ? <span><i className="pf-key pf-key--dd" aria-hidden="true" />낙폭(고점 대비)</span> : <span className="pf-legend-none">낙폭 곡선 없음</span>}
      </p>
      {/* 증거 띠 범례 — 글자가 띠의 뜻을 말한다(색·빗금만으로 말하지 않는다) */}
      <p className="pf-strip-legend">
        {learnW > 0 && <span><i className="pf-skey pf-skey--learn" aria-hidden="true" />처음 {learnDays}일은 배우기만</span>}
        {rebalLegend && <span>{rebalIdx.length > 0 && <i className="pf-skey pf-skey--rebal" aria-hidden="true" />}{rebalLegend}</span>}
        {asOfIdx !== null && asOfIdx >= 0 && view.asOf && <span><i className="pf-skey pf-skey--asof" aria-hidden="true" />기준일 {view.asOf.slice(0, 10)}</span>}
        {view.practice === true && <span className="pf-strip-legend-practice"><i className="pf-skey pf-skey--practice" aria-hidden="true" />연습용 데이터</span>}
        {view.practice === null && <span className="pf-strip-legend-unknown">데이터가 실제인지 몰라요</span>}
      </p>
    </div>
  );
}
