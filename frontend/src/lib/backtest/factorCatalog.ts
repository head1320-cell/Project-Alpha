// 대상 경로: frontend/src/lib/backtest/factorCatalog.ts
//
// 젠포트 팩터 가이드(v1.82)에서 추출한 344개 팩터 카탈로그.
// 데이터는 genportFactors.json 에 있고 여기서 타입을 입혀 노출한다.
// (카테고리 분류는 휴리스틱이라 일부 보정 필요. 팩터 이름·{토큰}은 가이드와 일치.)
//
// next.config.js 에 resolveJsonModule 가 기본 켜져 있으므로 JSON import 가능.
// 아니면 tsconfig 의 compilerOptions.resolveJsonModule: true 확인.

import raw from "./genportFactors.json";

export interface GpFactor {
  /** 팩터 이름 (예: "고가") */
  name: string;
  /** 조건식 입력 원형 (예: "{고가}", "이격도점수({N일})") */
  expr: string;
}

export interface GpFactorCategory {
  id: string;
  label: string;
  factors: GpFactor[];
}

export const FACTOR_SOURCE: string = (raw as { source: string }).source;
export const FACTOR_TOTAL: number = (raw as { total: number }).total;
export const FACTOR_CATEGORIES: GpFactorCategory[] = (raw as { categories: GpFactorCategory[] }).categories;

/** 팩터 이름 -> 입력 토큰. 함수가 없을 때 미리보기 기본값으로 사용 */
export function factorToken(name: string): string {
  const f = FACTOR_CATEGORIES.flatMap((c) => c.factors).find((x) => x.name === name);
  // expr 가 "{이름}" 형태면 그대로, 함수형(이격도점수({N일}))이면 {이름}로 단순화
  if (f && /^\{[^{}]+\}$/.test(f.expr)) return f.expr;
  return `{${name}}`;
}

/** 검색: 카테고리 라벨 또는 팩터 이름에 q 가 포함된 것 */
export function searchFactors(q: string): { category: GpFactorCategory; factor: GpFactor }[] {
  const t = q.trim();
  if (!t) return [];
  const lc = t.toLowerCase();
  const hits: { category: GpFactorCategory; factor: GpFactor }[] = [];
  for (const c of FACTOR_CATEGORIES) {
    for (const f of c.factors) {
      if (f.name.toLowerCase().includes(lc)) hits.push({ category: c, factor: f });
    }
  }
  return hits;
}
