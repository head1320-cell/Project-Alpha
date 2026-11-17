/**
 * 매매 몫 결합(K4) 결과 판의 서식 — 순수 함수(논리 스펙 `e2e/canvas-core-satellite-logic.spec.ts` 가 건다)
 * ==========================================================================
 * 서버는 퍼센트 값(×100 · 넷째 자리까지)을 싣고 화면은 ★그대로★ 서식한다 — 100 으로 나눴다 다시 곱하면 27.45 가 27.4499… 가 되어
 * 27.4% 로 보였다(E2E 에서 찾음). 부호는 보이는 자릿수로 0 이면 붙이지 않는다. 모르면 N/A(0 이 아니다).
 */
import { UNKNOWN_TEXT, num } from "@/shared/lib/krFormat";

const finite = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** 서버의 퍼센트 값 → "24.65%" · 음수는 빼기 기호(U+2212). */
export const pctOf = (v: unknown, digits: number): string => {
  const x = finite(v);
  return x === null ? UNKNOWN_TEXT : `${num(x, digits)}%`;
};

/** 부호를 붙인 퍼센트 → "+1.50%" · "−1.50%" · 보이는 자릿수로 0 이면 "0.00%". */
export const signedOf = (v: unknown, digits: number): string => {
  const x = finite(v);
  if (x === null) return UNKNOWN_TEXT;
  return `${x > 0 && Number(x.toFixed(digits)) !== 0 ? "+" : ""}${num(x, digits)}%`;
};

/** 시행 · 국면 등급 — E0(합성) · E3(실데이터)만 그대로, 그 밖은 미상. */
export const gradeOf = (v: unknown): string => (v === "E0" || v === "E3" ? v : "미상");

/** 핵심(정책 백테스트)의 시세 — 성과 라벨의 모의 여부. 모르면 미상(실제라고 하지 않는다). */
export const coreOf = (v: unknown): string => (v === true ? "모의 시세" : v === false ? "실제 시세" : "미상");
