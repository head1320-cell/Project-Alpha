// 매크로 콕핏 → 백테스터 전략 셋업 전달 (탭 간 전체 백테스트 구성 이식)
// screenerHandoff와 동일 패턴: 모듈 store + sessionStorage 폴백.
// 전략 백테스트 버튼이 backtest-config(mode별 구성)를 담아 백테스터가 그대로 셋업.

import type { StrategyBacktestConfig } from "@/lib/screenerApi";

export interface MacroBacktestHandoff {
  config: StrategyBacktestConfig;
  createdAt: number;
}

const KEY = "alpha:macro-handoff";

let _handoff: MacroBacktestHandoff | null = null;
const _listeners = new Set<() => void>();

export function setMacroHandoff(h: MacroBacktestHandoff) {
  _handoff = h;
  try { sessionStorage.setItem(KEY, JSON.stringify(h)); } catch { /* 메모리만 */ }
  _listeners.forEach((fn) => fn());
}

export function getMacroHandoff(): MacroBacktestHandoff | null {
  if (_handoff) return _handoff;
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) { _handoff = JSON.parse(raw) as MacroBacktestHandoff; return _handoff; }
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
