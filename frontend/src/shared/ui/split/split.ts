/**
 * 창 구분선의 순수 규칙 — 키 · 끌기로 한 칸의 폭(정수 px)을 정한다(G5 · 계획 문서 §6.2).
 * ==========================================================================
 * side = "start": 구분선 앞(왼쪽) 칸의 폭 — → 가 넓히고 ← 가 좁힌다 · 오른쪽으로 끈 만큼 넓어진다.
 * side = "end":   구분선 뒤(오른쪽) 칸의 폭 — ← 가 넓히고 → 가 좁힌다 · 왼쪽으로 끈 만큼 넓어진다(캔버스 오른쪽 판).
 * Home 은 최소 · End 는 최대(WAI-ARIA 창 구분선). 결과는 늘 [최소, 최대] 안의 정수 — 최대가 최소보다 작으면(칸이 좁으면) 최소.
 */
export type SplitSide = "start" | "end";

/** 반올림한 정수 px 를 [min, max] 안으로. 수가 아니면 min(지어내지 않는다 — 가장 좁은 폭으로 그린다). */
export function clampSplit(w: number, min: number, max: number): number {
  if (!Number.isFinite(w)) return Math.round(min);
  return Math.round(Math.min(Math.max(min, max), Math.max(min, w)));
}

/** 키 하나 → 새 폭. 이 구분선이 다루지 않는 키는 null(부르는 쪽이 기본 동작을 막지 않는다). */
export function splitByKey(key: string, value: number, o: { min: number; max: number; step: number; side: SplitSide }): number | null {
  const grow = o.side === "start" ? "ArrowRight" : "ArrowLeft";
  const shrink = o.side === "start" ? "ArrowLeft" : "ArrowRight";
  const next = key === grow ? value + o.step : key === shrink ? value - o.step : key === "Home" ? o.min : key === "End" ? o.max : null;
  return next === null ? null : clampSplit(next, o.min, o.max);
}

/** 끌기 — 누른 때의 폭 w0 · 누른 x0 에서 지금 x 까지 옮긴 만큼. */
export function splitByDrag(w0: number, x0: number, x: number, side: SplitSide, min: number, max: number): number {
  return clampSplit(side === "start" ? w0 + (x - x0) : w0 + (x0 - x), min, max);
}
