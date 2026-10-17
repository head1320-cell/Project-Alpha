/**
 * 작은 그림의 글자 (BM C1) — 서버 `glance` 점 값을 **그대로** 글로 옮긴다. 값을 바꾸지 않고 자릿수만 고른다.
 * ★모르는 값은 "모름"★ — `null`·NaN 을 0 으로 적지 않는다.
 */
export function fmtGlance(v: number | null, unit: string | null): string {
  if (v === null || !Number.isFinite(v)) return "모름";
  const a = Math.abs(v);
  const n = v === 0 ? "0" : a >= 1000 ? Math.round(v).toLocaleString("ko-KR") : a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : v.toFixed(3);
  if (!unit) return n;
  return unit === "%" ? `${n}%` : `${n}${unit === "원" ? "원" : ` ${unit}`}`;
}

/** 계산 시간 — 1ms 미만은 0 이라 적지 않고 "1ms 미만", 1초 미만은 ms, 그 위는 초. */
export function fmtElapsed(ms: number): string {
  if (ms < 1) return "1ms 미만";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}초`;
}
