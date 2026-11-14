/**
 * 매매일지 화면의 글자 서식 — 값은 서버가 준 그대로, 여기서는 자릿수와 부호만 정한다.
 * ★미상 ≠ 0★ `null` 은 `N/A` 로 그린다(0원·0% 로 그리지 않는다). 사유는 부르는 자리가 옆에 적는다.
 */
import { MINUS, UNKNOWN_TEXT, num } from "@/shared/lib/krFormat";
import type { CostBasis } from "@/entities/trade-journal";

type N = number | null | undefined;
const ok = (v: N): v is number => typeof v === "number" && Number.isFinite(v);

/** 손익 — 부호를 늘 붙인다(+27,175원 · −13,970원 · 0원). 원 단위 그대로(만·억으로 줄이지 않는다). */
export function signedWon(v: N): string {
  if (!ok(v)) return UNKNOWN_TEXT;
  const r = Math.round(Math.abs(v));
  return `${r === 0 ? "" : v < 0 ? MINUS : "+"}${num(r)}원`;
}

/** 금액(비용·대금·하락 폭) — 부호 없는 크기. */
export const amountWon = (v: N): string => (ok(v) ? `${num(Math.abs(v))}원` : UNKNOWN_TEXT);

/** 배수(손익비 · Profit Factor) — 소수 둘째 자리. */
export const ratio2 = (v: N): string => (ok(v) ? v.toFixed(2) : UNKNOWN_TEXT);

export const sign = (v: N): "up" | "down" | "flat" => (!ok(v) || Math.round(v) === 0 ? "flat" : v > 0 ? "up" : "down");

/** 수량 — 정수면 그대로, 소수면 넷째 자리까지. */
export const qty = (v: N): string => (ok(v) ? v.toLocaleString("ko-KR", { maximumFractionDigits: 4 }) : UNKNOWN_TEXT);

/** 보유 시간(초) → "40초" · "3분" · "3시간 0분" · "1일 0시간". 시각이 없는 체결이면 `null` 이 온다. */
export function holdText(seconds: N): string {
  if (!ok(seconds)) return UNKNOWN_TEXT;
  if (seconds < 60) return `${seconds}초`;
  if (seconds < 3_600) return `${Math.floor(seconds / 60)}분`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3_600)}시간 ${Math.floor((seconds % 3_600) / 60)}분`;
  return `${Math.floor(seconds / 86_400)}일 ${Math.floor((seconds % 86_400) / 3_600)}시간`;
}

/** 서버 시각("2026-03-04T09:00:40") → "2026-03-04 09:00:40". 시각이 없는 체결(날짜만)이면 날짜만. */
export const whenText = (iso: string | null | undefined, hasTime = true): string =>
  !iso ? UNKNOWN_TEXT : hasTime ? iso.slice(0, 19).replace("T", " ") : iso.slice(0, 10);

/** 수수료율(bp) → "0.100%". */
export const bpAsPct = (bp: N): string => (ok(bp) ? `${(bp / 100).toFixed(3)}%` : UNKNOWN_TEXT);

/** 비용의 근거 → 화면 낱말(저장소의 증거 어휘). */
export const BASIS_KO: Record<CostBasis, string> = {
  observed: "관측", inferred: "추론", assumed: "가정", unknown: "미상", not_applicable: "해당 없음",
};
export const MARKET_KO: Record<string, string> = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스" };
export const INSTRUMENT_KO: Record<string, string> = { stock: "주식", etf: "ETF" };
