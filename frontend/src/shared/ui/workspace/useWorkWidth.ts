"use client";
/**
 * 상자 폭 재기 — 콜백 ref + ResizeObserver(늦게 붙는 요소도 잰다). 폭 0(가려진 때)은 무시하고 앞 값을 둔다.
 * G5 `useSplitPane` 의 재기와 같은 길이다(그 훅은 분봉 두 칸의 상태까지 지녀 여기서 쓰지 않는다 — G5 의 계약을 건드리지 않으려고 따로 둔다).
 */
import { useCallback, useRef, useState } from "react";

export function useWorkWidth(): [(el: HTMLElement | null) => void, number] {
  const [width, setWidth] = useState(0);
  const ro = useRef<ResizeObserver | null>(null);
  const measure = useCallback((el: HTMLElement | null) => {
    ro.current?.disconnect();
    ro.current = null;
    if (!el) return;
    const read = () => { const w = el.clientWidth; if (w > 0) setWidth((prev) => (Math.abs(prev - w) < 1 ? prev : w)); };
    read();
    if (typeof ResizeObserver === "undefined") return;
    ro.current = new ResizeObserver(read);
    ro.current.observe(el);
  }, []);
  return [measure, width];
}
