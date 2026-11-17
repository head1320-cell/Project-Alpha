/**
 * 시장 국면의 글자와 색 — 확률은 소수 한 자리 퍼센트, 값이 없으면 N/A(0 이 아니다 · 용어집 §2).
 * 색은 토큰(`--itd-mr-s1..s7` · 라이트/다크 짝)에서 고른다 — 국면 수 2 · 3 · 4 에 1·7 / 1·4·7 / 1·3·5·7 단(같은 간격 · dataviz 순서형 검사 통과).
 */
import { num, pct, UNKNOWN_TEXT } from "@/shared/lib/krFormat";

const STEPS: Record<number, number[]> = { 2: [1, 7], 3: [1, 4, 7], 4: [1, 3, 5, 7] };

/** 국면 s(1부터) 의 칠 — 모르는 국면 수면 중립색(지어내지 않는다). */
export function stateFill(s: number, k: number): string {
  const step = STEPS[k]?.[s - 1];
  return step ? `var(--itd-mr-s${step})` : "var(--tx-mute)";
}

export const probText = (p: number | null | undefined): string => (typeof p === "number" && Number.isFinite(p) ? pct(p, 1) : UNKNOWN_TEXT);

/** 일 로그 수익의 평균 — 부호를 붙인 퍼센트(소수 두 자리). */
export function dailyText(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return UNKNOWN_TEXT;
  const body = pct(v, 2);
  return body.startsWith("−") || Number(Math.abs(v * 100).toFixed(2)) === 0 ? body : `+${body}`;
}

/** 연율 변동성 — 퍼센트(소수 한 자리). */
export const volText = (v: number | null | undefined): string => (typeof v === "number" && Number.isFinite(v) ? pct(v, 1) : UNKNOWN_TEXT);

/** BIC — 소수 한 자리(서버 값 그대로 · 고르지 않는다). */
export const bicText = (v: number | null | undefined): string => (typeof v === "number" && Number.isFinite(v) ? num(v, 1) : UNKNOWN_TEXT);
