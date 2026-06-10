// 체결가 유형 카탈로그 — 백엔드 src/engine/fill_price.py 의 FILL_PRICE_LABELS / FILL_PRICE_GROUPS 미러.
// (id·라벨 변경 시 양쪽 동기화. 서버에서도 GET /api/v1/screener/fill-price-types 로 제공)

export interface FillPriceOption { id: string; label: string }
export interface FillPriceGroup { id: string; label: string; options: FillPriceOption[] }

export const FILL_PRICE_GROUPS: FillPriceGroup[] = [
  { id: "current", label: "당일", options: [
    { id: "close", label: "당일 종가" },
    { id: "open", label: "당일 시초가" },
  ]},
  { id: "prev", label: "전일", options: [
    { id: "prev_close", label: "전일 종가" },
    { id: "prev_open", label: "전일 시초가" },
    { id: "prev_high", label: "전일 고가" },
    { id: "prev_low", label: "전일 저가" },
  ]},
  { id: "pivot", label: "피벗", options: [
    { id: "pivot", label: "피벗 기준선" },
    { id: "pivot_r1", label: "피벗 1차 저항선" },
    { id: "pivot_r2", label: "피벗 2차 저항선" },
    { id: "pivot_s1", label: "피벗 1차 지지선" },
    { id: "pivot_s2", label: "피벗 2차 지지선" },
  ]},
  { id: "avg", label: "평균가", options: [
    { id: "twap", label: "TWAP (시간가중)" },
    { id: "vwap", label: "VWAP (거래량가중)" },
  ]},
];

export function fillPriceLabel(id: string): string {
  for (const g of FILL_PRICE_GROUPS) {
    const t = g.options.find((o) => o.id === id);
    if (t) return t.label;
  }
  return id;
}
