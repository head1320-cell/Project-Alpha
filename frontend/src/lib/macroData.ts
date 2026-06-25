// ═══════════════════════════════════════════════════════════════════════════════
// macroData — Macro Allocation Cockpit 데이터 로더 (실API 조립, 병렬)
//   코어: regime + dashboard(6테마) + valuation + strategies(us) + recommend(us) 병렬.
//   lazy: 시장토글(strategies/recommend by market) · 지표 드릴다운(series 36M).
//   전부 실데이터(키 있으면) — 없으면 백엔드가 결정론적 mock 폴백(패널별 출처 배지로 정직 표기).
// ═══════════════════════════════════════════════════════════════════════════════
import { analysisApi, type MacroStrategies, type MacroRecommend, type MacroDashboard, type MacroValuation } from "@/lib/screenerApi";
import { macroApi, type RegimeState, type MacroSeries } from "@/lib/macroApi";

export type Market = "us" | "kr";

export interface MacroCore {
  regime: RegimeState | null;
  dashboard: MacroDashboard | null;
  valuation: MacroValuation | null;
  strategies: MacroStrategies | null; // 기본 us
  recommend: MacroRecommend | null;   // 기본 us
}

export async function loadMacroCore(): Promise<MacroCore> {
  const [regime, dashboard, valuation, strategies, recommend] = await Promise.all([
    macroApi.regime().catch(() => null),
    analysisApi.macroDashboard().catch(() => null),
    analysisApi.macroValuation().catch(() => null),
    analysisApi.macroStrategies("us").catch(() => null),
    analysisApi.macroRecommend("us").catch(() => null),
  ]);
  return { regime, dashboard, valuation, strategies, recommend };
}

// ── 시장 토글 lazy (US⇄KR) ──
export const loadStrategies = (m: Market): Promise<MacroStrategies | null> =>
  analysisApi.macroStrategies(m).catch(() => null);
export const loadRecommend = (m: Market): Promise<MacroRecommend | null> =>
  analysisApi.macroRecommend(m).catch(() => null);

// ── 지표 드릴다운 lazy (36개월 시계열 + mean/std/percentile) ──
export const loadSeries = (indicator: string): Promise<MacroSeries | null> =>
  macroApi.series(indicator).catch(() => null);

// 4-Quadrant 해소 (regime 문자열 → 축 폴백). 백엔드 라벨이 Goldilocks/Deflation일 수 있어 매핑.
export function resolveQuadrant(regime: RegimeState | null): "Reflation" | "Overheating" | "Stagflation" | "Disinflation" {
  if (!regime) return "Disinflation";
  const n = (regime.regime || "").toLowerCase();
  if (n.includes("overheat")) return "Overheating";
  if (n.includes("stagflation")) return "Stagflation";
  if (n.includes("reflation") || n.includes("goldilocks")) return "Reflation";
  if (n.includes("disinflation") || n.includes("deflation")) return "Disinflation";
  const g = regime.growth_axis ?? 0, i = regime.inflation_axis ?? 0;
  if (g >= 0) return i >= 0 ? "Overheating" : "Reflation";
  return i >= 0 ? "Stagflation" : "Disinflation";
}
