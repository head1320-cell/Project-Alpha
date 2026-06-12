// 대상 경로: frontend/src/lib/backtest/conditionSets.ts
//
// 조건식 세트 저장/불러오기 (젠포트 매수/매도 조건의 "불러오기·저장하기").
// 전략 전체 저장(strategyLibrary)과 별개로, 조건 리스트+논리식만 이름 붙여 보관.
// localStorage 기반 — 서버 불필요, 최대 50개.

import type { Condition } from "../../components/backtest/ConditionFormulaEditor";

export interface SavedConditionSet {
  id: string;
  name: string;
  side: "buy" | "sell";
  conditions: Condition[];
  logicExpr: string;
  savedAt: string;
}

const KEY = "alpha_condition_sets";
const MAX = 50;

export function listConditionSets(side?: "buy" | "sell"): SavedConditionSet[] {
  if (typeof window === "undefined") return [];
  try {
    const all: SavedConditionSet[] = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return side ? all.filter((s) => s.side === side) : all;
  } catch {
    return [];
  }
}

export function saveConditionSet(
  name: string, side: "buy" | "sell", conditions: Condition[], logicExpr: string,
): SavedConditionSet {
  const all = listConditionSets();
  const item: SavedConditionSet = {
    id: `cset_${Date.now()}`,
    name: name.trim() || `조건식 ${all.length + 1}`,
    side, conditions, logicExpr,
    savedAt: new Date().toISOString(),
  };
  all.unshift(item);
  localStorage.setItem(KEY, JSON.stringify(all.slice(0, MAX)));
  return item;
}

export function deleteConditionSet(id: string): void {
  localStorage.setItem(KEY, JSON.stringify(listConditionSets().filter((s) => s.id !== id)));
}

/** 불러올 때 조건 id 재발급 — 같은 세트를 두 번 불러와도 키 충돌 없게 */
export function cloneConditions(conditions: Condition[]): Condition[] {
  return conditions.map((c) => ({ ...c, id: Math.random().toString(36).slice(2, 9) }));
}
