"use client";
/**
 * 창 구분선 하나(WAI-ARIA window splitter) — 키(←/→ · Home · End)와 끌기(포인터 붙잡기)로 한 칸의 폭을 정한다.
 * ==========================================================================
 * 규칙은 `split.ts`(순수) 한 곳 — 캔버스 오른쪽 판(side end)과 분봉 화면의 설정 칸(side start)이 같은 부품을 쓴다(G5 · 계획 문서 §6).
 * ★스타일이 없다★ — 클래스 · 이름은 부르는 쪽이 준다(캔버스의 `.pg-side-resize` 는 그대로). `onChange(w, done)` — 끄는 동안 false, 놓거나 키를 누르면 true.
 * Enter 는 `onEnter` 를 준 쪽에서만 쓴다(칸 접기 — APG). 최대가 최소보다 작아도 aria-valuemax 는 최소 아래로 내려가지 않는다.
 */
import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { splitByDrag, splitByKey, type SplitSide } from "./split";

export function Splitter({ value, min, max, step, side, label, className, controls, onChange, onEnter }: {
  value: number; min: number; max: number; step: number; side: SplitSide; label: string; className: string;
  controls?: string; onChange: (w: number, done: boolean) => void; onEnter?: () => void;
}) {
  const drag = useRef<{ x: number; w: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" && onEnter) { e.preventDefault(); onEnter(); return; }
    const next = splitByKey(e.key, value, { min, max, step, side });
    if (next === null) return;
    e.preventDefault();
    onChange(next, true);
  };
  const at = (x: number) => (drag.current ? splitByDrag(drag.current.w, drag.current.x, x, side, min, max) : value);
  const move = (e: PointerEvent<HTMLDivElement>) => { if (drag.current) onChange(at(e.clientX), false); };
  const end = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onChange(at(e.clientX), true);
    drag.current = null;
    setDragging(false);
  };
  return (
    <div className={className} role="separator" aria-orientation="vertical" aria-label={label}
         aria-valuemin={min} aria-valuemax={Math.max(min, max)} aria-valuenow={value} aria-controls={controls} tabIndex={0}
         data-drag={dragging || undefined} onKeyDown={onKey}
         onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, w: value }; setDragging(true); }}
         onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
  );
}
