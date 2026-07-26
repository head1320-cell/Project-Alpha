// ═══════════════════════════════════════════════════════════════════════════════
// macroData — Macro Allocation Cockpit 데이터 로더 (실API 조립, 병렬)
//   코어: regime + dashboard(6테마) + valuation + strategies(us) + recommend(us) 병렬.
//   lazy: 시장토글(strategies/recommend by market) · 지표 드릴다운(series 36M).
//   전부 실데이터(키 있으면) — 없으면 백엔드가 결정론적 mock 폴백(패널별 출처 배지로 정직 표기).
// ═══════════════════════════════════════════════════════════════════════════════
import { analysisApi } from "./analysisApi";
import { type MacroCorrelations, type MacroDashboard, type MacroRecommend, type MacroStrategies, type MacroTiming, type MacroTrajectory, type MacroValuation, type StrategyAI, type StrategyBacktestConfig, type StrategyDetail } from "./analysisModel";
import { macroApi, type RegimeState, type MacroSeries } from "@/entities/macro/api";

export type Market = "us" | "kr";

export interface MacroCore {
  regime: RegimeState | null;
  dashboard: MacroDashboard | null;
  valuation: MacroValuation | null;
  strategies: MacroStrategies | null; // 기본 kr (국내 ETF 실데이터)
  recommend: MacroRecommend | null;   // 기본 kr
}

// ── 시장 토글 lazy (US⇄KR) ──
export const loadStrategies = (m: Market): Promise<MacroStrategies | null> =>
  analysisApi.macroStrategies(m).catch(() => null);
export const loadRecommend = (m: Market): Promise<MacroRecommend | null> =>
  analysisApi.macroRecommend(m).catch(() => null);

// ── 지표 드릴다운 lazy (36개월 시계열 + mean/std/percentile) ──
export const loadSeries = (indicator: string): Promise<MacroSeries | null> =>
  macroApi.series(indicator).catch(() => null);

// ── 상관/타이밍/궤적 lazy (탭 진입 시 — 계산 무거워 코어와 분리) ──
export const loadCorrelations = (m: Market): Promise<MacroCorrelations | null> =>
  analysisApi.macroCorrelations(m).catch(() => null);
export const loadTiming = (m: Market): Promise<MacroTiming | null> =>
  analysisApi.macroTiming(m).catch(() => null);
export const loadTrajectory = (): Promise<MacroTrajectory | null> =>
  analysisApi.macroTrajectory().catch(() => null);

// ── 전략 상세 모달 lazy ──
export const loadStrategyDetail = (sid: string, m: Market): Promise<StrategyDetail | null> =>
  analysisApi.macroStrategyDetail(sid, m).catch(() => null);
export const loadStrategyAI = (sid: string, m: Market): Promise<StrategyAI | null> =>
  analysisApi.macroStrategyAI(sid, m).catch(() => null);
export const loadStrategyBacktestConfig = (sid: string, m: Market): Promise<StrategyBacktestConfig | null> =>
  analysisApi.macroStrategyBacktestConfig(sid, m).catch(() => null);

// 4-Quadrant 해소 — 백엔드 regime_axes와 동일한 통일 명칭(Goldilocks/Reflation/Stagflation/Disinflation)
export type Quadrant = "Goldilocks" | "Reflation" | "Stagflation" | "Disinflation";

export function resolveQuadrant(regime: RegimeState | null): Quadrant {
  if (!regime) return "Disinflation";
  const n = (regime.regime || "").toLowerCase();
  if (n.includes("goldilocks")) return "Goldilocks";
  if (n.includes("stagflation")) return "Stagflation";
  if (n.includes("reflation") || n.includes("overheat")) return "Reflation";
  if (n.includes("deflation") || n.includes("disinflation")) return "Disinflation";
  const g = regime.growth_axis ?? 0, i = regime.inflation_axis ?? 0;
  if (g >= 0) return i >= 0 ? "Reflation" : "Goldilocks";
  return i >= 0 ? "Stagflation" : "Disinflation";
}
