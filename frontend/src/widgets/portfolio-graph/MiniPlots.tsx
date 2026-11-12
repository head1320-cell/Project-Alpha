"use client";
/**
 * 캔버스 결과의 작은 그림 셋 — 직접 SVG (2026-11-10 · ADR 004 §2.3 ㈏)
 * ==========================================================================
 * 프런티어(구름 + 경계 + 이은 비중) · 계단선(시점별 노출) · 수익률 곡선(뒤집힌 구간 칠하기).
 * 예전에는 recharts 였다 — 캔버스를 열기만 해도 그 조각(96 kB)이 왔고 값은 호버 툴팁에만 있었다. 이제 캔버스 묶음에 차트
 * 라이브러리가 없고(`e2e/charts-lazy.spec.ts`), 값은 ★읽는 줄★(←→ Home End)과 ★표 쌍둥이★에 늘 있다.
 * 수는 부르는 쪽이 서버 view 에서 꺼내 서식한 그대로다 — 여기서는 자리만 잡는다. 글자 크기를 고정하려고 폭을 직접 잰다.
 */
import { useMemo, useRef, type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from "react";
import { ReadLine, TableTwin, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { MARK } from "@/shared/ui/chart/chartSpec";
import { textW } from "@/shared/ui/perf/perfGeo";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";
import { gapPath, linScale, niceTicks, stepPath, tickDecimals, xyPath, type XY } from "@/shared/ui/plot/plotGeo";

const TOP = 8;
const RIGHT = 12;
const FALLBACK_W = 300;       // 옆 패널의 기본 안쪽 폭 — 재기 전 첫 그림

const pctTick = (ticks: number[]) => { const d = tickDecimals(ticks); return (v: number) => `${v.toFixed(d)}%`; };
const leftOf = (labels: string[]) => Math.max(30, Math.ceil(Math.max(0, ...labels.map(textW))) + 8);
/** 포인터의 그림 안 좌표(px). */
const at = (e: PointerEvent<SVGSVGElement>) => { const b = e.currentTarget.getBoundingClientRect(); return { px: e.clientX - b.left, py: e.clientY - b.top }; };
const nearest = (xs: number[], px: number) => xs.reduce((best, x, i) => (Math.abs(x - px) < Math.abs(xs[best] - px) ? i : best), 0);

/** 그림 + 읽는 줄 + 표 쌍둥이. 폭을 재는 상자가 바깥, 포커스·키보드·포인터는 svg(성과 그림 `PerfCurve` 와 같은 짜임). */
function Frame({ boxRef, label, width, height, onKeyDown, onPointer, row, rows, headLabel, children }: {
  boxRef: RefObject<HTMLDivElement | null>; label: string; width: number; height: number;
  onKeyDown: (e: KeyboardEvent) => void; onPointer: (e: PointerEvent<SVGSVGElement>) => void;
  row: ReadRow | null; rows: ReadRow[]; headLabel: string; children: ReactNode;
}) {
  return (
    <div ref={boxRef} className="pg-plot-box">
      <svg className="pg-plot" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="group" tabIndex={0}
           aria-label={`${label}. 화살표 키로 이동해 값을 읽습니다.`} onKeyDown={onKeyDown} onPointerMove={onPointer} onPointerDown={onPointer}>
        {children}
      </svg>
      <ReadLine row={row} />
      <TableTwin headLabel={headLabel} rows={rows} />
    </div>
  );
}

// ── 프런티어 — 흔들림(x) 대 수익(y) ─────────────────────────────────────────

/** `curve[i]` 와 `rows[i]` 는 같은 점이다. `initial` = 처음 읽을 점(가장 좋은 점). 단위는 서버 그대로(%). */
export function FrontierPlot({ dots, curve, point, rows, initial, label, height = 220 }: {
  dots: XY[]; curve: XY[]; point: XY | null; rows: ReadRow[]; initial: number; label: string; height?: number;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(boxRef, FALLBACK_W);
  const { idx, setIdx, onKeyDown } = useReadout(curve.length, initial);
  const geo = useMemo(() => {
    const all = [...dots, ...curve, ...(point ? [point] : [])];
    if (!all.length) return null;
    const xt = niceTicks(Math.min(...all.map((p) => p.x)), Math.max(...all.map((p) => p.x)), 4);
    const yt = niceTicks(Math.min(...all.map((p) => p.y)), Math.max(...all.map((p) => p.y)), 4);
    const fx = pctTick(xt), fy = pctTick(yt);
    const left = leftOf(yt.map(fy)), bottom = 34;                 // x 눈금 + 축 이름
    const sx = linScale(xt[0], xt[xt.length - 1], left, width - RIGHT);
    const sy = linScale(yt[0], yt[yt.length - 1], height - bottom, TOP);
    // 눈금 글자가 서로 닿으면 하나 걸러 — 끝 눈금에서부터 센다(끝은 늘 남는다)
    const room = (width - RIGHT - left) / Math.max(1, xt.length - 1);
    const every = room < Math.max(...xt.map((t) => textW(fx(t)))) + 8 ? 2 : 1;
    return { xt, yt, fx, fy, left, bottom, sx, sy, every };
  }, [dots, curve, point, width, height]);
  if (!geo) return <p className="pg-note">경계를 표시할 점 없음</p>;
  const { xt, yt, fx, fy, left, bottom, sx, sy, every } = geo;
  const cur = idx >= 0 ? curve[idx] : null;
  const onPointer = (e: PointerEvent<SVGSVGElement>) => {
    if (!curve.length) return;
    const { px, py } = at(e);
    let best = 0, bd = Infinity;
    curve.forEach((p, i) => { const d = (sx(p.x) - px) ** 2 + (sy(p.y) - py) ** 2; if (d < bd) { bd = d; best = i; } });
    setIdx(best);
  };
  return (
    <Frame boxRef={boxRef} label={label} width={width} height={height} onKeyDown={onKeyDown} onPointer={onPointer}
           row={idx >= 0 ? rows[idx] ?? null : null} rows={rows} headLabel="경계 위 점">
      {yt.map((t) => (
        <g key={`y${t}`}>
          <line className="pg-plot-grid" x1={left} x2={width - RIGHT} y1={sy(t)} y2={sy(t)} />
          <text className="pg-plot-ytick" x={left - 6} y={sy(t) + 3.5} textAnchor="end">{fy(t)}</text>
        </g>
      ))}
      {xt.map((t, i) => (
        <g key={`x${t}`}>
          <line className="pg-plot-grid" x1={sx(t)} x2={sx(t)} y1={TOP} y2={height - bottom} />
          {(xt.length - 1 - i) % every === 0 && <text className="pg-plot-xtick" x={sx(t)} y={height - bottom + 13} textAnchor="middle">{fx(t)}</text>}
        </g>
      ))}
      <text className="pg-plot-axis" x={(left + width - RIGHT) / 2} y={height - 4} textAnchor="middle">변동성(연)</text>
      {dots.map((p, i) => <circle key={i} className="pg-plot-dot" cx={sx(p.x)} cy={sy(p.y)} r={2} />)}
      {curve.length > 1 && <path className="pg-plot-line" d={xyPath(curve.map((p) => ({ x: sx(p.x), y: sy(p.y) })))} />}
      {cur && <circle className="pg-plot-active" cx={sx(cur.x)} cy={sy(cur.y)} r={MARK.dotR} />}
      {point && <circle className="pg-plot-point" cx={sx(point.x)} cy={sy(point.y)} r={7} />}
    </Frame>
  );
}

// ── 계단선 — 시점별 노출(0~100%) ───────────────────────────────────────────

/** `ys[i]`(%) 와 `rows[i]` 는 같은 시점이다(왼쪽이 옛날). 못 읽은 시점(null)은 0 이 아니라 끊긴 선. */
export function StepPlot({ ys, rows, label, height = 140 }: { ys: (number | null)[]; rows: ReadRow[]; label: string; height?: number }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(boxRef, FALLBACK_W);
  const n = ys.length;
  const { idx, setIdx, onKeyDown } = useReadout(n);
  const ticks = [0, 50, 100];
  const fy = (v: number) => `${v}%`;
  const left = leftOf(ticks.map(fy)), bottom = 18;
  const sy = linScale(0, 100, height - bottom, TOP);
  const sx = linScale(0, Math.max(1, n - 1), left, width - RIGHT);
  const xs = ys.map((_, i) => (n === 1 ? (left + width - RIGHT) / 2 : sx(i)));
  if (!n) return <p className="pg-note">그릴 시점 없음</p>;
  const py = ys.map((v) => (v === null ? null : sy(v)));
  const curY = idx >= 0 ? py[idx] : null;
  return (
    <Frame boxRef={boxRef} label={label} width={width} height={height} onKeyDown={onKeyDown} onPointer={(e) => setIdx(nearest(xs, at(e).px))}
           row={idx >= 0 ? rows[idx] ?? null : null} rows={rows} headLabel="시점">
      {ticks.map((t) => (
        <g key={t}>
          <line className="pg-plot-grid" x1={left} x2={width - RIGHT} y1={sy(t)} y2={sy(t)} />
          <text className="pg-plot-ytick" x={left - 6} y={sy(t) + 3.5} textAnchor="end">{fy(t)}</text>
        </g>
      ))}
      <path className="pg-plot-line pg-plot-line--step" d={stepPath(xs, py)} />
      {idx >= 0 && <line className="pg-plot-cross" x1={xs[idx]} x2={xs[idx]} y1={TOP} y2={height - bottom} />}
      {idx >= 0 && curY !== null && <circle className="pg-plot-active" cx={xs[idx]} cy={curY} r={MARK.dotR} />}
      <text className="pg-plot-xtick" x={left} y={height - 4} textAnchor="start">{rows[0]?.head ?? ""}</text>
      {n > 1 && <text className="pg-plot-xtick" x={width - RIGHT} y={height - 4} textAnchor="end">{rows[n - 1]?.head ?? ""}</text>}
    </Frame>
  );
}

// ── 수익률 곡선 — 만기(범주) 대 금리 ────────────────────────────────────────

/** `pts[i]` 와 `rows[i]` 는 같은 만기다. `dips` = 뒤집힌 이웃 쌍의 [왼쪽 순번, 오른쪽 순번](부르는 쪽이 찾는다). */
export function CurvePlot({ pts, dips, rows, label, height = 170 }: {
  pts: { t: string; y: number | null }[]; dips: [number, number][]; rows: ReadRow[]; label: string; height?: number;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(boxRef, FALLBACK_W);
  const n = pts.length;
  const { idx, setIdx, onKeyDown } = useReadout(n);
  const geo = useMemo(() => {
    const vals = pts.map((p) => p.y).filter((v): v is number => v !== null);
    if (!vals.length) return null;
    const yt = niceTicks(Math.min(...vals), Math.max(...vals), 4);
    const fy = pctTick(yt);
    const left = leftOf(yt.map(fy)), bottom = 20, pad = 14;        // 점이 축에 붙지 않게 안쪽 여백
    const sy = linScale(yt[0], yt[yt.length - 1], height - bottom, TOP + 12);   // 위 12px = 점 위 글자 자리
    const sx = linScale(0, Math.max(1, n - 1), left + pad, width - RIGHT - pad);
    const xs = pts.map((_, i) => (n === 1 ? (left + width - RIGHT) / 2 : sx(i)));
    // 점 위 금리 글자·만기 글자가 서로 닿으면 하나 걸러(값은 읽는 줄·표에 전부 있다)
    const room = n > 1 ? xs[1] - xs[0] : width;
    return { yt, fy, left, bottom, sy, xs, valEvery: room < 30 ? 2 : 1, tickEvery: room < Math.max(...pts.map((p) => textW(p.t))) + 6 ? 2 : 1 };
  }, [pts, n, width, height]);
  if (!geo) return <p className="pg-note">그릴 금리 점 없음</p>;
  const { yt, fy, left, bottom, sy, xs, valEvery, tickEvery } = geo;
  const py = pts.map((p) => (p.y === null ? null : sy(p.y)));
  const shown = (i: number, every: number) => (n - 1 - i) % every === 0;        // 마지막 점에서부터 센다(끝은 늘 남는다)
  return (
    <Frame boxRef={boxRef} label={label} width={width} height={height} onKeyDown={onKeyDown} onPointer={(e) => setIdx(nearest(xs, at(e).px))}
           row={idx >= 0 ? rows[idx] ?? null : null} rows={rows} headLabel="만기">
      {dips.map(([a, b]) => (
        <rect key={`${a}-${b}`} className="pg-curve-dip" x={xs[a]} y={TOP} width={Math.max(0, xs[b] - xs[a])} height={height - bottom - TOP} />
      ))}
      {yt.map((t) => (
        <g key={t}>
          <line className="pg-plot-grid" x1={left} x2={width - RIGHT} y1={sy(t)} y2={sy(t)} />
          <text className="pg-plot-ytick" x={left - 6} y={sy(t) + 3.5} textAnchor="end">{fy(t)}</text>
        </g>
      ))}
      <path className="pg-plot-line" d={gapPath(xs, py)} />
      {pts.map((p, i) => (
        <g key={`${p.t}-${i}`}>
          {py[i] !== null && <circle className="pg-curve-pt" cx={xs[i]} cy={py[i] as number} r={MARK.dotR + MARK.ring / 2} />}
          {py[i] !== null && shown(i, valEvery) && (
            <text className="pg-curve-val" x={xs[i]} y={(py[i] as number) - 7} textAnchor="middle">{(p.y as number).toFixed(2)}</text>
          )}
          {shown(i, tickEvery) && <text className="pg-plot-xtick" x={xs[i]} y={height - 5} textAnchor="middle">{p.t}</text>}
        </g>
      ))}
      {idx >= 0 && py[idx] !== null && <circle className="pg-plot-active" cx={xs[idx]} cy={py[idx] as number} r={MARK.dotR + 3.5} />}
    </Frame>
  );
}
