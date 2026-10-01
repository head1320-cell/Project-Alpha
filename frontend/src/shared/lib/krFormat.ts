// BU0 · 한국식 숫자 표기 한곳 (ADR-003 · 스펙 §7.1)
// ─────────────────────────────────────────────────────────────────────────────
// 새 화면(`shared/ui/tx`·토스식 모듈)은 숫자를 이 함수들로만 쓴다. 옛 `format.ts`(formatKrw·formatPct)는
// 기존 화면이 쓰는 그대로 둔다 — 모듈을 옮길 때 이쪽으로 바꾼다.
//
// ★미상 ≠ 0★ 유한하지 않은 값(null·undefined·NaN·±∞)은 "몰라요" 를 돌려준다 — `0`·`NaN`·`—` 로 그리지 않는다.
// 왜 모르는지 아는 호출자는 `shared/ui/tx` 의 `Unknown`(사유 필수)을 쓴다.
// ★비율과 퍼센트를 섞지 않는다★ `pct(0.241)` = "24.1%" — 입력은 늘 비율이다(0.241). 이미 퍼센트인 값은 100 으로 나눠 넣는다.

export const UNKNOWN_TEXT = "몰라요";
/** 음수 부호 — 하이픈(-) 대신 빼기 기호(U+2212). 숫자 폭이 맞고 화면 낭독기가 "마이너스"로 읽는다. */
export const MINUS = "−";

type N = number | null | undefined;
const ok = (v: N): v is number => typeof v === "number" && Number.isFinite(v);
const group = (v: number, digits: number) =>
  v.toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
/** 부호 — 보이는 자릿수로 반올림해 0 이 되면 부호를 붙이지 않는다(−0.0% 를 만들지 않는다). */
const sign = (v: number, signed: boolean, digits = 0) => {
  const r = Number(Math.abs(v).toFixed(digits));
  return r === 0 ? "" : v < 0 ? MINUS : signed ? "+" : "";
};

/** 1234.5 → "1,235" · digits=1 → "1,234.5" */
export function num(v: N, digits = 0): string {
  if (!ok(v)) return UNKNOWN_TEXT;
  return sign(v, false, digits) + group(Math.abs(v), digits);
}

/** 한국식 큰 수 — 1.2조 · 3,400억 · 5,600만 · 1,234. 조는 소수 한 자리, 억·만은 정수(반올림). */
export function krUnit(v: N): string {
  if (!ok(v)) return UNKNOWN_TEXT;
  const a = Math.abs(v), s = sign(v, false);
  // 작은 단위부터 — 반올림이 다음 단위에 닿으면(9,999.6만 → 10,000만) 큰 단위로 넘긴다(→ 1억).
  if (Math.round(a) < 1e4) return s + group(Math.round(a), 0);
  const man = Math.round(a / 1e4);
  if (a < 1e8 && man < 1e4) return `${s}${group(man, 0)}만`;
  const eok = Math.round(a / 1e8);
  if (a < 1e12 && eok < 1e4) return `${s}${group(eok, 0)}억`;
  return `${s}${group(Math.round(a / 1e11) / 10, 1)}조`;
}

/** 원 — 만 이상은 한국식 단위(3,400억원), 그 아래는 그대로(1,234원). */
export function won(v: N): string {
  if (!ok(v)) return UNKNOWN_TEXT;
  return `${krUnit(v)}원`;
}

/** 비율 → 퍼센트. pct(0.241) = "24.1%" · pct(-0.03) = "−3.0%" */
export function pct(ratio: N, digits = 1): string {
  if (!ok(ratio)) return UNKNOWN_TEXT;
  const p = ratio * 100;
  return `${sign(p, false, digits)}${group(Math.abs(p), digits)}%`;
}

/** 부호를 늘 붙인 퍼센트(수익률·등락). signedPct(0.241) = "+24.1%" · 0 → "0.0%" */
export function signedPct(ratio: N, digits = 1): string {
  if (!ok(ratio)) return UNKNOWN_TEXT;
  const p = ratio * 100;
  return `${sign(p, true, digits)}${group(Math.abs(p), digits)}%`;
}

/** 퍼센트포인트 — 두 비율의 차이. pp(0.021) = "+2.1%p" */
export function pp(ratioDiff: N, digits = 1): string {
  if (!ok(ratioDiff)) return UNKNOWN_TEXT;
  const p = ratioDiff * 100;
  return `${sign(p, true, digits)}${group(Math.abs(p), digits)}%p`;
}

/** 등락 방향 — 색과 ▲▼ 를 고르는 데 쓴다. 미상은 "unknown"(평평함과 다르다). */
export type Direction = "up" | "down" | "flat" | "unknown";
export function direction(v: N): Direction {
  if (!ok(v)) return "unknown";
  return v > 0 ? "up" : v < 0 ? "down" : "flat";
}
