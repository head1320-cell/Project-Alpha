"use client";
/**
 * 칸 사이 가로 구분선(WAI-ARIA window splitter · 가로) — 값은 아래 칸의 비율(20 ~ 80%) (G6 2a-1 · 계획 §9.1)
 * ==========================================================================
 * ↑ 아래 칸 넓힘 · ↓ 좁힘(5% 걸음) · Home 최소 · End 최대 · 끌기(포인터 붙잡기 · 위로 끈 만큼 넓어짐). 규칙은 `layout.ts` 의 `rowByKey` · `rowByDrag`(순수).
 * G5 의 `Splitter`(세로 · px)는 그대로 두고 따로 둔다 — 축 · 단위가 다르고 G5 의 캔버스 · 두 칸 계약을 건드리지 않는다.
 * `onChange(h, done)` — 끄는 동안 false(그리기만), 놓거나 키를 누르면 true(남긴다).
 */
import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { H_MAX, H_MIN, rowByDrag, rowByKey } from "./layout";

export function RowSplitter({ value, label, className, style, hidden, heightOf, onChange }: {
  value: number; label: string; className: string; style?: CSSProperties; hidden?: boolean;
  /** 비율을 셀 높이(작업 공간 그리드의 높이). */
  heightOf: () => number;
  onChange: (h: number, done: boolean) => void;
}) {
  const drag = useRef<{ y: number; h: number; height: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const pct = Math.round(value * 100);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = rowByKey(e.key, value);
    if (next === null) return;
    e.preventDefault();
    onChange(next, true);
  };
  const at = (y: number) => (drag.current ? rowByDrag(drag.current.h, drag.current.y, y, drag.current.height) : value);
  const end = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onChange(at(e.clientY), true);
    drag.current = null;
    setDragging(false);
  };
  return (
    <div className={className} style={style} hidden={hidden} role="separator" aria-orientation="horizontal" aria-label={label}
         aria-valuemin={Math.round(H_MIN * 100)} aria-valuemax={Math.round(H_MAX * 100)} aria-valuenow={pct} aria-valuetext={`아래 칸 ${pct}%`}
         tabIndex={0} data-drag={dragging || undefined} onKeyDown={onKey}
         onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { y: e.clientY, h: value, height: heightOf() }; setDragging(true); }}
         onPointerMove={(e) => { if (drag.current) onChange(at(e.clientY), false); }} onPointerUp={end} onPointerCancel={end} />
  );
}
