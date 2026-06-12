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
    { id: "pivot", label: "피벗 주가중심선" },
    { id: "pivot_mid", label: "피벗 기준선" },
    { id: "pivot_r1", label: "피벗 1차 저항선" },
    { id: "pivot_r2", label: "피벗 2차 저항선" },
    { id: "pivot_s1", label: "피벗 1차 지지선" },
    { id: "pivot_s2", label: "피벗 2차 지지선" },
  ]},
  { id: "ma", label: "이동평균 (전일까지)", options: [
    { id: "ma5", label: "5일 이동평균" },
    { id: "ma10", label: "10일 이동평균" },
    { id: "ma20", label: "20일 이동평균" },
    { id: "ma60", label: "60일 이동평균" },
    { id: "ma120", label: "120일 이동평균" },
    { id: "ma200", label: "200일 이동평균" },
  ]},
  { id: "avg", label: "평균가", options: [
    { id: "twap", label: "TWAP (시간가중)" },
    { id: "vwap", label: "VWAP (거래량가중)" },
  ]},
  { id: "expr", label: "수식", options: [
    { id: "expr", label: "수식입력" },
  ]},
];

/** 만기 매도 등 수식입력을 받지 않는 위치용 (expr 그룹 제외) */
export const FILL_PRICE_GROUPS_NO_EXPR: FillPriceGroup[] =
  FILL_PRICE_GROUPS.filter((g) => g.id !== "expr");

export function fillPriceLabel(id: string): string {
  for (const g of FILL_PRICE_GROUPS) {
    const t = g.options.find((o) => o.id === id);
    if (t) return t.label;
  }
  return id;
}
