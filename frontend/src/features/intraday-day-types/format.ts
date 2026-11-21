/**
 * 하루 유형의 글자 — bp 는 부호를 늘 붙이고(빼기 기호 U+2212) 소수 한 자리. 값이 없으면 N/A(0 이 아니다).
 * 서버가 지은 글자(손실 · 일치도)는 여기서 다시 짓지 않는다 — 그대로 보인다.
 */
import { MINUS, num, UNKNOWN_TEXT } from "@/shared/lib/krFormat";

export function bpText(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return UNKNOWN_TEXT;
  const body = num(v, 1);                                           // "−12.3" · "12.3" · "0.0"
  return `${body.startsWith(MINUS) || Number(Math.abs(v).toFixed(1)) === 0 ? body : `+${body}`}bp`;
}

/** 크기(부호 없는 bp) — 흩어짐처럼 방향이 없는 값. */
export function bpSize(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return UNKNOWN_TEXT;
  return `${num(v, 1)}bp`;
}

/** 축 눈금 — 단위 없이(축 아래 줄이 'bp'라고 말한다). */
export function bpTick(v: number): string {
  return num(v, Math.abs(v) >= 100 ? 0 : 1);
}

/** "0901" → "09:01" */
export const clock = (hhmm: string): string => (hhmm.length >= 4 ? `${hhmm.slice(0, 2)}:${hhmm.slice(2, 4)}` : hhmm);
