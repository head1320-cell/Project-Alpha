"use client";
/**
 * 붙는 문장 띠(`.ma-stick`)의 높이(패딩 포함) — 내 계좌 판 배치(G6 2a-2 · 계획 §10.1)의 작업 공간 높이 = 창 − 띠 를 CSS 변수로 넘긴다
 * (문장 길이 · 칩 · 창 폭에 따라 바뀐다). 콜백 ref + ResizeObserver(공용 `useWorkWidth` 와 같은 길 · 값이 바뀔 때만 다시 그린다) · 0(가려진 때)은 무시하고 앞 값을 둔다.
 */
import { useCallback, useRef, useState } from "react";

export function useBoxHeight(): [(el: HTMLElement | null) => void, number] {
  const [height, setHeight] = useState(0);
  const ro = useRef<ResizeObserver | null>(null);
  const measure = useCallback((el: HTMLElement | null) => {
    ro.current?.disconnect();
    ro.current = null;
    if (!el) return;
    const read = () => { const h = el.getBoundingClientRect().height; if (h > 0) setHeight((prev) => (Math.abs(prev - h) < 1 ? prev : h)); };
    read();
    if (typeof ResizeObserver === "undefined") return;
    ro.current = new ResizeObserver(read);
    ro.current.observe(el);
  }, []);
  return [measure, height];
}
