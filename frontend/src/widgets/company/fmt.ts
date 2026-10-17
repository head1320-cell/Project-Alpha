// 기업 분석 안쪽 절(BU6b)의 숫자 서식 — 한곳에 모은다.
// ★null·NaN = "몰라요"(0 과 다르다)★ · 음수는 U+2212 · 금액은 억/조 + "원"(옛 "항목(억원)" 머리처럼 단위를 거짓으로 말하지 않게 칸마다 단위).
import { UNKNOWN_TEXT, MINUS } from "@/shared/lib/krFormat";

type N = number | null | undefined;
export const ok = (v: N): v is number => typeof v === "number" && Number.isFinite(v);
const sign = (v: number) => (v < 0 ? MINUS : "");

/** 억 단위 금액 → "3,400억원" · "1.2조원"(1조 이상) · 모르면 "몰라요". */
export function eokWon(v: N): string {
  if (!ok(v)) return UNKNOWN_TEXT;
  const a = Math.abs(v);
  if (a >= 10000) return `${sign(v)}${(a / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}조원`;
  return `${sign(v)}${Math.round(a).toLocaleString("ko-KR")}억원`;
}
/** 원 단위 → "20,596원". */
export function wonTxt(v: N): string {
  return ok(v) ? `${sign(v)}${Math.round(Math.abs(v)).toLocaleString("ko-KR")}원` : UNKNOWN_TEXT;
}
/** 이미 % 인 값 → "8.1%". */
export function pctTxt(v: N, d = 1): string {
  return ok(v) ? `${sign(v)}${Math.abs(v).toFixed(d)}%` : UNKNOWN_TEXT;
}
/** 부호 붙은 %p → "+1.72%p" / "−2.40%p". */
export function ppSigned(v: N, d = 2): string {
  return ok(v) ? `${v > 0 ? "+" : sign(v)}${Math.abs(v).toFixed(d)}%p` : UNKNOWN_TEXT;
}
/** 부호 붙은 % → "+3.0%". */
export function pctSigned(v: N, d = 1): string {
  return ok(v) ? `${v > 0 ? "+" : sign(v)}${Math.abs(v).toFixed(d)}%` : UNKNOWN_TEXT;
}
/** 배수 → "4.32배". */
export function bae(v: N, d = 2): string {
  return ok(v) ? `${sign(v)}${Math.abs(v).toLocaleString("ko-KR", { maximumFractionDigits: d })}배` : UNKNOWN_TEXT;
}
/** 그냥 수 → "1.083" · 음수 U+2212. */
export function plain(v: N, d = 2): string {
  return ok(v) ? `${sign(v)}${Math.abs(v).toLocaleString("ko-KR", { maximumFractionDigits: d })}` : UNKNOWN_TEXT;
}
/** "2025" → "2025년" · "2025Q3" → "2025년 3분기" · 서버 연도 숫자 → "2025년". */
export function periodKo(p: string | number): string {
  const s = String(p);
  const m = /^(\d{4})Q([1-4])$/.exec(s);
  if (m) return `${m[1]}년 ${m[2]}분기`;
  return /^\d{4}$/.test(s) ? `${s}년` : s;
}
/** 표 머리용 짧은 기간 — "2025" → "25년" · "2025Q3" → "25.3분기". */
export function periodShort(p: string | number): string {
  const s = String(p);
  const m = /^(\d{4})Q([1-4])$/.exec(s);
  if (m) return `${m[1].slice(2)}.${m[2]}분기`;
  return /^\d{4}$/.test(s) ? `${s.slice(2)}년` : s;
}
