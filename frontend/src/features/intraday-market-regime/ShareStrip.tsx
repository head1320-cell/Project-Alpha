"use client";
/**
 * 하루 유형 비중 그림 — 판정 기간의 날마다 그날 국면이 쓴 비중(전 거래일까지 20거래일 · 0 ~ 100%) (구현 계획 §7.6 · K5 · ADR 004 손그림 SVG)
 * ==========================================================================
 * 막대 하나가 하루이고 높이가 비중이다. 색은 한 가지 — 비중은 국면이 아니라 국면 색과 섞지 않는다.
 * 모르는 날은 0 이 아니라 빗금 막대 + '미상 · 사유'(서버 문장 그대로). 툴팁 0 — ←→ Home End · 포인터로 날을 옮겨 읽는 줄 · 표 쌍둥이.
 * 값은 서버 값을 서식만 한다(`data-value` 에는 받은 수 그대로 — 시험이 서버 값과 견준다).
 */
import { useId, useMemo, useRef, type PointerEvent } from "react";
import type { ShareDay } from "@/entities/intraday";
import { pct, UNKNOWN_TEXT } from "@/shared/lib/krFormat";
import { ReadLine, TableTwin, useReadout, type ReadRow } from "@/shared/ui/chart/ChartReadout";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";

const H = 84;
const L = 4, R = 4, TOP = 6, BOTTOM = 20;

export function ShareStrip({ days }: { days: ShareDay[] }) {
  const wrap = useRef<HTMLDivElement>(null);
  const hatch = `itd-mrs-hatch-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const width = useMeasuredWidth(wrap, 640);
  const n = days.length;
  const { idx, setIdx, onKeyDown } = useReadout(n, n - 1);
  const plotW = Math.max(40, width - L - R);
  const plotH = H - TOP - BOTTOM;
  const step = n > 0 ? plotW / n : plotW;

  const rows: ReadRow[] = useMemo(() => days.map((d) => ({
    head: d.date,
    cells: [
      { key: "value", label: "비중", text: d.value === null ? `미상 · ${d.message ?? "사유 미상"}` : pct(d.value, 1) },
      { key: "samples", label: "창의 표본", text: d.value === null ? UNKNOWN_TEXT : `${d.samples.toLocaleString("ko-KR")}개` },
    ],
  })), [days]);

  const pick = (e: PointerEvent<SVGSVGElement>) => {
    if (n <= 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    setIdx(Math.min(n - 1, Math.max(0, Math.floor((e.clientX - box.left - L) / step))));
  };
  const first = days[0]?.date ?? "", last = days[n - 1]?.date ?? "";
  const aria = `하루 유형 비중 그림. ${first}부터 ${last}까지 ${n}일. 화살표 키로 날을 옮겨 값을 읽습니다.`;
  return (
    <div className="itd-mrs-share" ref={wrap} role="group" tabIndex={0} aria-label={aria} onKeyDown={onKeyDown} data-chart="day-type-share">
      <svg className="itd-mrs-share-svg" width={width} height={H} aria-hidden="true" onPointerMove={pick} onPointerDown={pick}>
        <defs>
          <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="itd-mr-hatch-line" />
          </pattern>
        </defs>
        <line x1={L} x2={L + plotW} y1={TOP + plotH} y2={TOP + plotH} className="itd-mrs-share-base" />
        {days.map((d, i) => {
          const x = L + i * step, w = Math.max(1, step);
          if (d.value === null) {
            return (
              <g key={d.date} className="itd-mrs-share-day" data-day={d.date} data-value="unknown">
                <rect x={x} y={TOP} width={w} height={plotH} fill={`url(#${hatch})`} className="itd-mrs-share-unknown" />
              </g>
            );
          }
          const h = Math.max(0, Math.min(1, d.value)) * plotH;
          return (
            <g key={d.date} className="itd-mrs-share-day" data-day={d.date} data-value={String(d.value)}>
              {h > 0 ? <rect x={x} y={TOP + plotH - h} width={w} height={h} className="itd-mrs-share-bar" /> : null}
            </g>
          );
        })}
        {idx >= 0 ? <rect x={L + idx * step} y={TOP - 3} width={Math.max(2, step)} height={plotH + 6} className="itd-mr-cursor" /> : null}
        <text x={L} y={H - 5} className="pf-xtick" textAnchor="start">{first}</text>
        <text x={L + plotW} y={H - 5} className="pf-xtick" textAnchor="end">{last}</text>
      </svg>
      <p className="itd-mrs-share-axis">막대 하나가 하루이고 높이가 그날 국면이 쓴 비중입니다(바닥 0%, 위 끝 100%). 빗금은 비중을 모르는 날입니다.</p>
      <ReadLine row={idx >= 0 ? rows[idx] ?? null : null} />
      <TableTwin headLabel="날짜" rows={rows} />
    </div>
  );
}
