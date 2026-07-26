// 자산군 프리셋 (젠포트 자산배분 옵션 — 중립형/공격형/안정형). 직접설정은 빈 바스켓.
// ETF 코드·이름은 대표 KODEX 상품 (마스터 적재 시 검색으로 교체·추가 가능).

import type { BasketLeg } from "./strategy";

export interface AssetPreset {
  id: "neutral" | "aggressive" | "stable" | "custom";
  label: string;
  basket: BasketLeg[];
}

export const ASSET_PRESETS: AssetPreset[] = [
  {
    id: "neutral", label: "중립형", basket: [
      { ticker: "069500", name: "KODEX 200", weightPct: 50 },
      { ticker: "273130", name: "KODEX 종합채권(AA-이상)액티브", weightPct: 50 },
    ],
  },
  {
    id: "aggressive", label: "공격형", basket: [
      { ticker: "069500", name: "KODEX 200", weightPct: 60 },
      { ticker: "122630", name: "KODEX 레버리지", weightPct: 30 },
      { ticker: "273130", name: "KODEX 종합채권(AA-이상)액티브", weightPct: 10 },
    ],
  },
  {
    id: "stable", label: "안정형", basket: [
      { ticker: "069500", name: "KODEX 200", weightPct: 30 },
      { ticker: "273130", name: "KODEX 종합채권(AA-이상)액티브", weightPct: 70 },
    ],
  },
  { id: "custom", label: "직접설정", basket: [] },
];

export function presetBasket(id: AssetPreset["id"]): BasketLeg[] {
  return (ASSET_PRESETS.find((p) => p.id === id)?.basket ?? []).map((l) => ({ ...l }));
}
