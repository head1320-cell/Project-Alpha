"use client";
import { useEffect, useState, type RefObject } from "react";

/**
 * 그림 폭을 px 로 잰다(ResizeObserver) — viewBox 로 늘리면 글자까지 커지므로, 폭 300~960px 어디서든 글자 크기를 고정하려고 직접 잰다.
 * 처음 그릴 때(아직 못 쟀을 때)는 `fallback` 으로 그리고 잰 뒤 한 번 다시 그린다.
 */
export function useMeasuredWidth(ref: RefObject<HTMLElement | null>, fallback = 344): number {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => { const cw = el.clientWidth; if (cw > 0) setW((prev) => (Math.abs(prev - cw) < 1 ? prev : cw)); };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}
