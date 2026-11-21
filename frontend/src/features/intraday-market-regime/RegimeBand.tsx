"use client";
/**
 * 시장 국면 띠 — 날마다 막대 하나(국면 확률을 쌓은 것) + 읽는 줄 + 표 쌍둥이 (구현 계획 §7.1 · K1 · ADR 004 손그림 SVG)
 * ==========================================================================
 * 국면 번호는 ★변동성이 낮은 것부터★ 매긴 순서라 한 색상의 밝기 단계로 칠한다(`--itd-mr-s1..s7` · 국면 수에 따라 단을 고른다).
 * 바탕에 가장 가까운 단이 국면 1 이다(라이트에서 가장 옅고 다크에서 가장 어둡다). 색만으로 말하지 않는다 — 범례의 번호 · 읽는 줄 · 표 쌍둥이.
 * 값이 없는 날은 0 이 아니라 빗금 막대 + '국면 미상 · 사유'(서버 문장 그대로). 툴팁 0 — ←→ Home End · 포인터로 날을 옮긴다.
 * 빗금 무늬의 id 는 그림마다 따로다 — 한 화면에 띠가 둘(지수만 · 하루 유형 비중을 더한 답 · K5)이어도 겹치지 않는다.
 */
import { useId, useMemo, useRef, type PointerEvent } from "react";
import type { MarketRegimeDay } from "@/entities/intraday";
import { ReadLine, TableTwin, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";
import { probText, stateFill } from "./format";

const H = 96;
const L = 4, R = 4, TOP = 6, BOTTOM = 20;

export function RegimeBand({ days, k }: { days: MarketRegimeDay[]; k: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const hatch = `itd-mr-hatch-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const width = useMeasuredWidth(wrap, 640);
  const n = days.length;
  const { idx, setIdx, onKeyDown } = useReadout(n, n - 1);
  const plotW = Math.max(40, width - L - R);
  const plotH = H - TOP - BOTTOM;
  const step = n > 0 ? plotW / n : plotW;

  const rows: ReadRow[] = useMemo(() => days.map((d) => ({
    head: d.date,
    cells: [
      ...Array.from({ length: k }, (_, s) => ({ key: `s${s + 1}`, label: `국면 ${s + 1}`, text: probText(d.probs?.[s]) })),
      { key: "top", label: "가장 큰", text: d.top === null ? `국면 미상 · ${d.reason ?? "사유 미상"}` : `국면 ${d.top}` },
    ],
  })), [days, k]);

  const pick = (e: PointerEvent<SVGSVGElement>) => {
    if (n <= 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    setIdx(Math.min(n - 1, Math.max(0, Math.floor((e.clientX - box.left - L) / step))));
  };
  const first = days[0]?.date ?? "", last = days[n - 1]?.date ?? "";
  const anyUnknown = days.some((d) => !d.probs);                       // 범례에는 그린 것만 — 빗금 막대가 있을 때만 '미상'
  const aria = `시장 국면 확률 띠. ${first}부터 ${last}까지 ${n}일, 국면 ${k}개. 화살표 키로 날을 옮겨 값을 읽습니다.`;
  return (
    <div className="itd-mr-fig" ref={wrap} role="group" tabIndex={0} aria-label={aria} onKeyDown={onKeyDown} data-chart="market-regime">
      <svg className="itd-mr-svg" width={width} height={H} aria-hidden="true" onPointerMove={pick} onPointerDown={pick}>
        <defs>
          <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="itd-mr-hatch-line" />
          </pattern>
        </defs>
        {days.map((d, i) => {
          const x = L + i * step, w = Math.max(1, step);
          if (!d.probs) {
            return (
              <g key={d.date} className="itd-mr-day" data-day={d.date} data-top="unknown">
                <rect x={x} y={TOP} width={w} height={plotH} fill={`url(#${hatch})`} className="itd-mr-unknown" />
              </g>
            );
          }
          let y = TOP + plotH;                                      // 아래부터 국면 1 — 칸 높이 = 그 국면의 확률
          return (
            <g key={d.date} className="itd-mr-day" data-day={d.date} data-top={String(d.top)}>
              {d.probs.map((p, s) => {
                const h = Math.max(0, p) * plotH;
                y -= h;
                return h > 0 ? <rect key={s} x={x} y={y} width={w} height={h} style={{ fill: stateFill(s + 1, k) }} /> : null;
              })}
            </g>
          );
        })}
        {idx >= 0 ? <rect x={L + idx * step} y={TOP - 3} width={Math.max(2, step)} height={plotH + 6} className="itd-mr-cursor" /> : null}
        <text x={L} y={H - 5} className="pf-xtick" textAnchor="start">{first}</text>
        <text x={L + plotW} y={H - 5} className="pf-xtick" textAnchor="end">{last}</text>
      </svg>
      <ul className="itd-mr-legend" aria-label="국면 번호">
        {Array.from({ length: k }, (_, s) => (
          <li key={s}><i style={{ background: stateFill(s + 1, k) }} aria-hidden="true" />국면 {s + 1}</li>
        ))}
        {anyUnknown ? <li><i className="itd-mr-legend-unknown" aria-hidden="true" />미상</li> : null}
      </ul>
      <p className="itd-mr-axis">막대 하나가 하루입니다. 아래부터 국면 1 이며 번호는 적합 창에서 20거래일 실현 변동성의 평균이 낮은 국면부터 매겼습니다. 막대의 칸 높이가 그 국면의 소속 확률입니다.</p>
      <ReadLine row={idx >= 0 ? rows[idx] ?? null : null} />
      <TableTwin headLabel="날짜" rows={rows} />
    </div>
  );
}
