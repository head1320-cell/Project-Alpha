// 스크리너 → 백테스터 전략 전달 (탭 간 조건식 전송)
// Next.js 클라이언트 라우팅에서 모듈 상태가 유지되므로 간단한 전역 store로 충분.
// sessionStorage 폴백으로 새로고침에도 일부 대응.

import type { FilterGroupNode } from "@/shared/model/domain";

export interface ScreenerStrategyHandoff {
  filterAst: FilterGroupNode;
  universe: string;
  conditionSummary: string[];  // 사람이 읽는 조건 요약
  resultCount: number;          // 스크리너에서 매칭된 종목 수
  createdAt: number;
}

const KEY = "alpha:screener-handoff";

let _handoff: ScreenerStrategyHandoff | null = null;
const _listeners = new Set<() => void>();

export function setScreenerHandoff(h: ScreenerStrategyHandoff) {
  _handoff = h;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(h));
  } catch { /* sessionStorage 불가 시 메모리만 */ }
  _listeners.forEach((fn) => fn());
}

export function getScreenerHandoff(): ScreenerStrategyHandoff | null {
  if (_handoff) return _handoff;
  // 새로고침 후 복원 시도
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      _handoff = JSON.parse(raw) as ScreenerStrategyHandoff;
      return _handoff;
    }
  } catch { /* noop */ }
  return null;
}

export function clearScreenerHandoff() {
  _handoff = null;
  try { sessionStorage.removeItem(KEY); } catch { /* noop */ }
  _listeners.forEach((fn) => fn());
}

export function subscribeHandoff(fn: () => void): () => void {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
