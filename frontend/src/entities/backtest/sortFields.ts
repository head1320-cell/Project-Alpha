import type { ScreenerItem } from "@/shared/model";
// 매수 우선순위 정렬 필드 — 백엔드 ScreenerItem 속성과 1:1 (screen-to-backtest sort_by).
// 후보 풀 정렬 = 엔진 매수 순회 순서 → 동시 신호 시 매수 우선순위가 된다.

export const SORT_FIELDS: { id: string; label: string }[] = [
  { id: "composite_score", label: "종합점수" },
  { id: "market_cap_억", label: "시가총액" },
  { id: "per", label: "PER" },
  { id: "pbr", label: "PBR" },
  { id: "roe_pct", label: "ROE" },
  { id: "dividend_yield_pct", label: "배당수익률" },
  { id: "gap_pct", label: "내재가치 괴리율" },
  { id: "momentum_12_1", label: "모멘텀 (12-1)" },
  { id: "amount_20d_avg", label: "거래대금 (20일)" },
];

export function sortFieldLabel(id: string): string {
  return SORT_FIELDS.find((f) => f.id === id)?.label ?? id;
}
