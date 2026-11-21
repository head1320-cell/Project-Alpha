"use client";
/**
 * 봉 그림 — 1분봉 + 거래량 띠 + 체결 표식 + 범례 + 하루 전체 띠 + 읽는 줄 + 표 쌍둥이 (G4 · 구현 계획 §5 · §5.7 · ADR 004 손그림 SVG)
 * ==========================================================================
 * 좌표는 `candleGeo` 가 셈하고 여기는 그리기만 한다. FSD 의 shared 라 평범한 값만 받는다(봉 · 체결 · 읽는 줄의 줄들).
 *   · 등락은 색만으로 말하지 않는다 — 양봉은 빈 몸통(테두리 `--tx-up`) · 음봉은 채운 몸통(`--tx-down`) · 보합은 가로선. 범례와 읽는 줄도 글로 적는다.
 *   · 체결은 매수 ▲(봉 아래) · 매도 ▼(봉 위)의 ★모양★과 몸통 밖 체결가 눈금(매수 왼쪽 · 매도 오른쪽) · 같은 봉 여러 체결은 묶고 수를 적는다.
 *   · 툴팁 0 · `<canvas>` 0 · 차트 라이브러리 0 — 값은 늘 보이는 읽는 줄(←→ Home End · 포인터)과 표 쌍둥이에.
 *   · 가격 눈금은 넘기지 않는 왼쪽 축(따로 그린 SVG · 같은 y)에 · 봉 그림만 틀(`.cdl-scroll`) 안에서 옆으로 넘긴다. 읽는 자리를 옮기면 그 봉이 보이게 따라간다.
 *   · 그림이 틀보다 넓으면 아래 '하루 전체' 띠(종가 선 · 체결 자리 · 보이는 구간 창)와 `보이는 구간` 글 — 띠를 누르거나 누른 채 옮기면 그 자리가 가운데 온다.
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { ReadLine, TableTwin, useReadout, type ReadRow } from "./ChartReadout";
import {
  barAtStrip, candleLayout, overviewLayout, overviewWindow, visibleRange, type CandleBar, type CandleFill, type CandleMark,
} from "./candleGeo";
import { useMeasuredWidth } from "@/shared/ui/perf/useMeasuredWidth";

const TRI_W = 5, TRI_H = 7;
const OVERVIEW_H = 36;

function triangle(m: CandleMark): string {
  const b = m.side === "buy" ? m.tip + TRI_H : m.tip - TRI_H;           // 매수 ▲ 는 꼭짓점이 위 · 매도 ▼ 는 아래
  return `M ${m.x} ${m.tip} L ${m.x + TRI_W} ${b} L ${m.x - TRI_W} ${b} Z`;
}

/** 범례 — 그림과 ★같은 클래스★로 칠한 작은 글리프 + 글(범례의 색 = 그림의 색). */
function Legend() {
  return (
    <ul className="cdl-legend" aria-label="그림의 표식">
      <li><svg className="cdl-glyph" width="14" height="12" aria-hidden="true"><g className="cdl-mark-buy"><path className="cdl-tri" d="M 7 1 L 12 10 L 2 10 Z" /></g></svg>매수 체결</li>
      <li><svg className="cdl-glyph" width="14" height="12" aria-hidden="true"><g className="cdl-mark-sell"><path className="cdl-tri" d="M 2 2 L 12 2 L 7 11 Z" /></g></svg>매도 체결</li>
      <li>
        <svg className="cdl-glyph" width="22" height="12" aria-hidden="true">
          <g className="cdl-flat"><rect className="cdl-glyph-box" x="8" y="2" width="6" height="8" /></g>
          <g className="cdl-mark-buy"><line className="cdl-tick" x1="1" x2="6" y1="5" y2="5" /></g>
          <g className="cdl-mark-sell"><line className="cdl-tick" x1="16" x2="21" y1="7" y2="7" /></g>
        </svg>
        체결가(매수 왼쪽 · 매도 오른쪽 눈금)
      </li>
      <li><svg className="cdl-glyph" width="14" height="12" aria-hidden="true"><g className="cdl-up"><line className="cdl-wick" x1="7" x2="7" y1="0" y2="12" /><rect className="cdl-body" x="4" y="3" width="6" height="6" /></g></svg>양봉(빈 몸통)</li>
      <li><svg className="cdl-glyph" width="14" height="12" aria-hidden="true"><g className="cdl-down"><line className="cdl-wick" x1="7" x2="7" y1="0" y2="12" /><rect className="cdl-body" x="4" y="3" width="6" height="6" /></g></svg>음봉(채운 몸통)</li>
      <li><svg className="cdl-glyph" width="14" height="12" aria-hidden="true"><g className="cdl-flat"><line className="cdl-wick" x1="7" x2="7" y1="1" y2="11" /><line className="cdl-flat-line" x1="3" x2="11" y1="6" y2="6" /></g></svg>보합(가로선)</li>
    </ul>
  );
}

export function CandleChart({ id, label, bars, fills, rows, priceText, height = 300, initial }: {
  /** `data-chart` 이름(E2E 가 그림을 가리키는 이름) */ id: string;
  /** 그림이 무엇인지 — 스크린 리더가 읽는 이름 */ label: string;
  bars: CandleBar[]; fills: CandleFill[];
  /** 봉마다 읽는 줄 하나(같은 순서) — 글자는 부르는 쪽이 서버 값을 서식해 넘긴다 */ rows: ReadRow[];
  /** 가격 눈금의 글자(원 단위 서식) */ priceText: (v: number) => string;
  height?: number; initial?: number;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(wrap, 640);
  const g = useMemo(() => candleLayout({ bars, fills, width, height }), [bars, fills, width, height]);
  const ov = useMemo(() => overviewLayout({ layout: g, bars, fills, height: OVERVIEW_H }), [g, bars, fills]);
  const n = bars.length;
  const { idx, setIdx, onKeyDown } = useReadout(n, initial);
  // 넘긴 자리 — 틀의 스크롤 사건으로만 받는다(코드가 scrollLeft 를 옮겨도 사건이 난다). 보이는 폭은 틀 폭 − 축 폭(`viewW`).
  const [left, setLeft] = useState(0);
  const wide = g.plotW > g.viewW + 1;

  useEffect(() => {                                                      // 읽는 자리가 틀 밖이면 그 봉이 보이게 옮긴다
    const s = scroller.current;
    if (!s || idx < 0 || !g.candles[idx]) return;
    const x = g.candles[idx].x, margin = 24;
    if (x < s.scrollLeft + margin) s.scrollLeft = Math.max(0, x - margin);
    else if (x > s.scrollLeft + s.clientWidth - margin) s.scrollLeft = x - s.clientWidth + margin;
  }, [idx, g]);

  const pick = (e: PointerEvent<SVGSVGElement>) => {
    if (n <= 0 || g.slot <= 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    setIdx(Math.min(n - 1, Math.max(0, Math.floor((e.clientX - box.left) / g.slot))));
  };
  const jump = (e: PointerEvent<SVGSVGElement>) => {                    // 하루 전체 띠: 누른 자리의 봉을 가운데로 · 읽는 줄도 그 봉으로
    const s = scroller.current;
    if (!s || n <= 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    const i = barAtStrip({ x: e.clientX - box.left, stripW: ov.width, plotW: g.plotW, slot: g.slot, n });
    s.scrollLeft = Math.min(Math.max(0, g.plotW - s.clientWidth), Math.max(0, g.candles[i].x - s.clientWidth / 2));
    setIdx(i);
  };
  const first = bars[0]?.time.slice(0, 5) ?? "", last = bars[n - 1]?.time.slice(0, 5) ?? "";
  const aria = `${label}. ${first}부터 ${last}까지 봉 ${n}개, 체결 표식 ${g.marks.length}개. 화살표 키로 봉을 옮겨 값을 읽습니다.`;
  const half = g.bodyW / 2;
  const seen = visibleRange({ scrollLeft: left, clientWidth: g.viewW, slot: g.slot, n });
  const win = overviewWindow({ scrollLeft: left, clientWidth: g.viewW, plotW: g.plotW, stripW: ov.width });
  return (
    <div className="cdl-fig" ref={wrap} role="group" tabIndex={0} aria-label={aria} onKeyDown={onKeyDown} data-chart={id}>
      <Legend />
      <div className="cdl-plotrow">
        <svg className="cdl-axis" width={g.axisW} height={height} aria-hidden="true">
          {g.priceTicks.map((t) => (
            <text key={t.value} className="cdl-plabel" x={g.axisW - 6} y={t.y} textAnchor="end" dominantBaseline="middle">{priceText(t.value)}</text>
          ))}
        </svg>
        <div className="cdl-scroll" ref={scroller} onScroll={(e) => setLeft(e.currentTarget.scrollLeft)}>
          <svg className="cdl" width={g.plotW} height={height} aria-hidden="true" onPointerMove={pick} onPointerDown={pick}>
            {g.priceTicks.map((t) => <line key={t.value} className="cdl-grid" x1={0} x2={g.plotW} y1={t.y} y2={t.y} />)}
            <line className="cdl-vol-base" x1={0} x2={g.plotW} y1={g.vol.bottom} y2={g.vol.bottom} />
            {g.candles.map((c) => (
              <g key={c.i} className={`cdl-candle cdl-${c.dir}`} data-i={c.i} data-time={bars[c.i].time}>
                <line className="cdl-wick" x1={c.x} x2={c.x} y1={c.wick.top} y2={c.wick.bottom} />
                {c.dir === "flat"
                  ? <line className="cdl-flat-line" x1={c.x - half} x2={c.x + half} y1={c.body.top} y2={c.body.top} />
                  : <rect className="cdl-body" x={c.x - half} y={c.body.top} width={g.bodyW} height={Math.max(1, c.body.bottom - c.body.top)} />}
                <rect className="cdl-vol" x={c.x - half} y={c.vol.top} width={g.bodyW} height={c.vol.bottom - c.vol.top} />
              </g>
            ))}
            {idx >= 0 && g.candles[idx] ? (
              <line className="cdl-cross" x1={g.candles[idx].x} x2={g.candles[idx].x} y1={g.price.top} y2={g.vol.bottom} />
            ) : null}
            {g.marks.map((m) => (
              <g key={`${m.i}-${m.side}`} className={`cdl-mark cdl-mark-${m.side}`} data-time={bars[m.i].time} data-count={m.fills.length}>
                {m.ticks.map((ty) => <line key={ty} className="cdl-tick" x1={m.tickX[0]} x2={m.tickX[1]} y1={ty} y2={ty} />)}
                <path className="cdl-tri" d={triangle(m)} />
                {m.fills.length > 1 ? (
                  <text className="cdl-count" x={m.x + TRI_W + 2} y={m.side === "buy" ? m.tip + TRI_H : m.tip - 2}>{`×${m.fills.length}`}</text>
                ) : null}
              </g>
            ))}
            {g.timeTicks.map((t) => (
              <text key={t.i} className="cdl-tlabel" x={t.x} y={height - 6} textAnchor="middle">{t.label}</text>
            ))}
          </svg>
        </div>
      </div>
      {wide ? (
        <>
          <svg className="cdl-overview" width={ov.width} height={OVERVIEW_H} aria-hidden="true"
               onPointerDown={(e) => { e.currentTarget.setPointerCapture?.(e.pointerId); jump(e); }}
               onPointerMove={(e) => { if (e.buttons & 1) jump(e); }}>
            <rect className="cdl-ov-bg" x={0} y={0} width={ov.width} height={OVERVIEW_H} />
            <polyline className="cdl-ov-line" points={ov.xs.map((x, i) => `${x},${ov.ys[i]}`).join(" ")} />
            {ov.ticks.map((t, k) => (
              <line key={k} className={`cdl-ov-tick cdl-ov-${t.side}`} x1={t.x} x2={t.x}
                    y1={t.side === "buy" ? OVERVIEW_H - 1 : 1} y2={t.side === "buy" ? OVERVIEW_H - 9 : 9} />
            ))}
            <rect className="cdl-ov-window" x={win.x} y={0.75} width={Math.max(2, win.w)} height={OVERVIEW_H - 1.5} />
          </svg>
          <p className="cdl-range">
            <span>{`보이는 구간 ${bars[seen.first]?.time.slice(0, 5) ?? ""} ~ ${bars[seen.last]?.time.slice(0, 5) ?? ""}`}</span>{" "}
            <span>{`(하루 ${first} ~ ${last})`}</span>
          </p>
        </>
      ) : null}
      <ReadLine row={idx >= 0 ? rows[idx] ?? null : null} />
      <TableTwin headLabel="시각" rows={rows} />
    </div>
  );
}
