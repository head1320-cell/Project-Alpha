/**
 * 시장 국면의 글자와 색 — 확률은 소수 한 자리 퍼센트, 값이 없으면 N/A(0 이 아니다 · 용어집 §2).
 * 색(`stateFill`)은 국면별 나눔(K2)과 함께 쓰려 `entities/intraday/regimeColor` 로 내렸다 — 여기서는 다시 내보내기만 한다.
 */
import { num, pct, UNKNOWN_TEXT } from "@/shared/lib/krFormat";

export { stateFill } from "@/entities/intraday";

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
