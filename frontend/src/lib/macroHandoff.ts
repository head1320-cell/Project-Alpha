// 매크로 콕핏 → 백테스터 자산배분 전달 (탭 간 추천 배분 이식)
// screenerHandoff와 동일 패턴: 모듈 store + sessionStorage 폴백.
// 매크로 추천/전략의 보유 ETF 바스켓을 백테스터 asset_alloc 슬리브로 프리필.

export interface MacroAllocLeg { ticker: string; name: string; weightPct: number }

export interface MacroAllocHandoff {
  strategyName: string;
  market: "us" | "kr";
  basket: MacroAllocLeg[];      // 합 ≈ 100 (정규화된 비중)
  rebalanceMonths: number;
  createdAt: number;
}

const KEY = "alpha:macro-handoff";

let _handoff: MacroAllocHandoff | null = null;
const _listeners = new Set<() => void>();

export function setMacroHandoff(h: MacroAllocHandoff) {
  _handoff = h;
  try { sessionStorage.setItem(KEY, JSON.stringify(h)); } catch { /* 메모리만 */ }
  _listeners.forEach((fn) => fn());
}

export function getMacroHandoff(): MacroAllocHandoff | null {
  if (_handoff) return _handoff;
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) { _handoff = JSON.parse(raw) as MacroAllocHandoff; return _handoff; }
  } catch { /* noop */ }
  return null;
}

export function clearMacroHandoff() {
  _handoff = null;
  try { sessionStorage.removeItem(KEY); } catch { /* noop */ }
  _listeners.forEach((fn) => fn());
}

export function subscribeMacroHandoff(fn: () => void): () => void {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
