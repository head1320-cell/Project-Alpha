"use client";
/**
 * 하루 유형의 중심 경로 — 유형마다 작은 판 하나(같은 세로축) + 읽는 줄 하나 + 표 쌍둥이 (ADR 004 · 손그림 SVG)
 * ==========================================================================
 * 한 판에 겹치지 않는 까닭: 유형은 최대 16개다. 색 열여섯으로 가르면 읽을 수 없다(dataviz '나눠 그리기'). 판마다 같은 세로축이라
 * 판 사이의 높낮이를 그대로 견줄 수 있다. 가로축은 ★첫 봉부터 m분째★다 — 표본마다 첫 봉 시각이 다를 수 있어 시계 시각이 아니다.
 * 툴팁 0 — 고른 분의 값은 그림 아래 읽는 줄에 늘 보이고, ←→ Home End · 포인터로 분을 옮긴다. 표 쌍둥이는 모든 분 × 모든 유형.
 * 표식은 성과 그림 문법(`pf-*`)을 그대로 쓴다 — 선 2px · 점 r4 + 표면색 고리 · 실선 격자 · 다크는 같은 역할 변수.
 */
import { useMemo, useRef, type PointerEvent } from "react";
import type { DayType } from "@/entities/intraday";
import { ReadLine, TableTwin, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { MARK } from "@/shared/ui/chart/chartSpec";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";
import { bpText, bpTick } from "./format";

const PANEL_MIN = 176;   // 판 하나의 최소 폭(px) — 이보다 좁으면 한 줄에 놓는 판 수를 줄인다
const GAP = 12;
const H = 128;
const L = 40, R = 10, TOP = 8, BOTTOM = 18;

export function DayTypeChart({ types, minutes }: { types: DayType[]; minutes: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(wrap, 640);
  const { idx, setIdx, onKeyDown } = useReadout(minutes, minutes - 1);

  const geo = useMemo(() => {
    const all = types.flatMap((t) => t.path);
    // 눈금은 ★실제 값★(모든 중심 경로의 최고 · 최저)에 · 그림의 범위는 0 을 넣고 위아래로 조금 넓힌다(점이 테두리에 붙지 않게).
    const top = Math.max(...all), bottom = Math.min(...all);
    let lo = Math.min(0, bottom), hi = Math.max(0, top);
    if (hi - lo < 1e-9) hi = lo + 1;
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    const cols = Math.max(1, Math.min(types.length, Math.floor((width + GAP) / (PANEL_MIN + GAP))));
    const w = Math.floor((width - GAP * (cols - 1)) / cols);
    return { lo, hi, top, bottom, cols, w };
  }, [types, width]);

  const rows: ReadRow[] = useMemo(() => Array.from({ length: minutes }, (_, m) => ({
    head: `${m + 1}분째`,
    cells: types.map((t) => ({ key: `t${t.type}`, label: `유형 ${t.type}`, text: bpText(t.path[m]) })),
  })), [types, minutes]);

  const aria = `하루 유형 ${types.length}개의 중심 경로. 첫 봉 시가 대비 bp, 첫 봉부터 ${minutes}분. 화살표 키로 분을 옮겨 값을 읽습니다.`;
  return (
    <div className="itd-dt-fig" data-chart="day-types">
      <div className="itd-dt-grid" ref={wrap} role="group" tabIndex={0} aria-label={aria} onKeyDown={onKeyDown}
           style={{ gridTemplateColumns: `repeat(${geo.cols}, minmax(0, 1fr))` }}>
        {types.map((t) => (
          <Panel key={t.type} t={t} w={geo.w} lo={geo.lo} hi={geo.hi} top={geo.top} bottom={geo.bottom} minutes={minutes} idx={idx}
                 onPick={setIdx} />
        ))}
      </div>
      <p className="itd-dt-axis">세로축: 첫 봉 시가 대비 bp(모든 판이 같은 눈금) · 가로축: 첫 봉부터 지난 분</p>
      <ReadLine row={idx >= 0 ? rows[idx] ?? null : null} />
      <TableTwin headLabel="첫 봉부터" rows={rows} />
    </div>
  );
}

function Panel({ t, w, lo, hi, top, bottom, minutes, idx, onPick }: {
  t: DayType; w: number; lo: number; hi: number; top: number; bottom: number; minutes: number; idx: number; onPick: (i: number) => void;
}) {
  const plotW = Math.max(20, w - L - R);
  const plotH = H - TOP - BOTTOM;
  const x = (i: number) => L + (minutes <= 1 ? 0 : (i / (minutes - 1)) * plotW);
  const y = (v: number) => TOP + (1 - (v - lo) / (hi - lo)) * plotH;
  const d = t.path.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const pick = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - box.left - L) / plotW) * (minutes - 1));
    onPick(Math.min(minutes - 1, Math.max(0, i)));
  };
  // 눈금 셋(최고 · 0 · 최저) — 글자가 겹칠 만큼 가까우면 뒤의 것을 그리지 않는다(0 은 늘 기준선으로 남는다).
  const ticks = [top, bottom].filter((v, i, a) => a.indexOf(v) === i && Math.abs(y(v) - y(0)) > 12);
  const shown = ticks.filter((v, i) => i === 0 || Math.abs(y(v) - y(ticks[0])) > 12);
  const cur = Math.min(minutes - 1, Math.max(0, idx));
  return (
    <figure className="itd-dt-panel" data-type={t.type} data-samples={t.samples}>
      <figcaption className="itd-dt-cap">
        <b>유형 {t.type}</b>
        <span className="itd-dt-samples">표본 {t.samples.toLocaleString("ko-KR")}개</span>
        <span className="itd-dt-end">끝 {bpText(t.end)}</span>
      </figcaption>
      <svg className="itd-dt-svg" width={w} height={H} aria-hidden="true" onPointerMove={pick} onPointerDown={pick}>
        {shown.map((v) => (
          <g key={v}>
            <line x1={L} x2={L + plotW} y1={y(v)} y2={y(v)} className="pf-grid" />
            <text x={L - 6} y={y(v) + 3.5} textAnchor="end" className="pf-ytick">{bpTick(v)}</text>
          </g>
        ))}
        <line x1={L} x2={L + plotW} y1={y(0)} y2={y(0)} className="pf-baseline" />
        <text x={L - 6} y={y(0) + 3.5} textAnchor="end" className="pf-ytick">0</text>
        <path d={d} className="pf-line-port itd-dt-line" />
        <line x1={x(cur)} x2={x(cur)} y1={TOP} y2={H - BOTTOM} className="pf-crossline" />
        <circle cx={x(cur)} cy={y(t.path[cur])} r={MARK.dotR + MARK.ring / 2} className="pf-dot pf-dot--port" />
        <text x={L} y={H - 4} className="pf-xtick" textAnchor="start">1분</text>
        <text x={L + plotW} y={H - 4} className="pf-xtick" textAnchor="end">{minutes}분</text>
      </svg>
    </figure>
  );
}
