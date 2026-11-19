"use client";
import { useSyncExternalStore } from "react";

/**
 * 미디어 쿼리가 지금 맞는지(창 크기가 바뀌면 다시 그린다). 서버 그림 · 수화 때는 false — 화면 배치를 서버가 지어내지 않는다.
 * matchMedia 가 없는 환경(오래된 브라우저 · 시험 환경)에서도 false.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = typeof window !== "undefined" ? window.matchMedia?.(query) : undefined;
      if (!mq) return () => undefined;
      mq.addEventListener?.("change", notify);
      return () => mq.removeEventListener?.("change", notify);
    },
    () => (typeof window !== "undefined" ? !!window.matchMedia?.(query).matches : false),
    () => false,
  );
}
