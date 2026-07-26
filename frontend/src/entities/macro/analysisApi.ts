// 매크로·전략·밸류에이션 분석 API.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type { ScreenerItem } from "@/shared/model/domain";
import type {
  AssetStrips,
  AxisHistory,
  CausalGraph,
  CbSentiment,
  CycleStrips,
  KrUsCompare,
  MacroCorrelations,
  MacroDashboard,
  MacroRecommend,
  MacroRegime,
  MacroStrategies,
  MacroTiming,
  MacroTrajectory,
  MacroValuation,
  StrategyAI,
  StrategyBacktestConfig,
  StrategyDetail,
} from "./analysisModel";

export const analysisApi = {
  macroRegime: async (): Promise<MacroRegime> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/regime`);
    if (!r.ok) throw new Error(`Macro regime failed: ${r.status}`);
    return r.json();
  },
  macroStrategies: async (market: "us" | "kr" = "kr"): Promise<MacroStrategies> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/strategies?market=${market}`);
    if (!r.ok) throw new Error(`Macro strategies failed: ${r.status}`);
    return r.json();
  },
  macroRecommend: async (market: "us" | "kr" = "kr"): Promise<MacroRecommend> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/recommend?market=${market}`);
    if (!r.ok) throw new Error(`Macro recommend failed: ${r.status}`);
    return r.json();
  },
  macroDashboard: async (): Promise<MacroDashboard> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/dashboard`);
    if (!r.ok) throw new Error(`Macro dashboard failed: ${r.status}`);
    return r.json();
  },
  macroValuation: async (): Promise<MacroValuation> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/valuation`);
    if (!r.ok) throw new Error(`Macro valuation failed: ${r.status}`);
    return r.json();
  },
  macroCorrelations: async (market: "us" | "kr" = "kr"): Promise<MacroCorrelations> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/correlations?market=${market}`);
    if (!r.ok) throw new Error(`Macro correlations failed: ${r.status}`);
    return r.json();
  },
  macroTiming: async (market: "us" | "kr" = "kr"): Promise<MacroTiming> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/timing?market=${market}`);
    if (!r.ok) throw new Error(`Macro timing failed: ${r.status}`);
    return r.json();
  },
  macroTrajectory: async (): Promise<MacroTrajectory> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/regime-trajectory`);
    if (!r.ok) throw new Error(`Macro trajectory failed: ${r.status}`);
    return r.json();
  },
  // v2: 중앙은행 센티먼트 게이지 + 그레인저 인과 그래프
  cbSentiment: async (): Promise<CbSentiment> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/cb-sentiment`);
    if (!r.ok) throw new Error(`CB sentiment failed: ${r.status}`);
    return r.json();
  },
  causalGraph: async (): Promise<CausalGraph> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/causal-graph`);
    if (!r.ok) throw new Error(`Causal graph failed: ${r.status}`);
    return r.json();
  },
  // v3: 사이클 스트립 · 하위요인 시계열 · 자산 스트립 · KR/US 비교
  cycleStrips: async (market: "kr" | "us" = "kr"): Promise<CycleStrips> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/cycle-strips?market=${market}`);
    if (!r.ok) throw new Error(`cycle-strips failed: ${r.status}`);
    return r.json();
  },
  axisHistory: async (market: "kr" | "us" = "kr"): Promise<AxisHistory> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/axis-history?market=${market}`);
    if (!r.ok) throw new Error(`axis-history failed: ${r.status}`);
    return r.json();
  },
  assetStrips: async (market: "kr" | "us" = "kr"): Promise<AssetStrips> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/asset-strips?market=${market}`);
    if (!r.ok) throw new Error(`asset-strips failed: ${r.status}`);
    return r.json();
  },
  compareKrUs: async (): Promise<KrUsCompare> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/compare-krus`);
    if (!r.ok) throw new Error(`compare-krus failed: ${r.status}`);
    return r.json();
  },
  macroStrategyDetail: async (sid: string, market: "us" | "kr" = "kr"): Promise<StrategyDetail> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/strategy/${sid}?market=${market}`);
    if (!r.ok) throw new Error(`Strategy detail failed: ${r.status}`);
    return r.json();
  },
  macroStrategyAI: async (sid: string, market: "us" | "kr" = "kr"): Promise<StrategyAI> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/strategy/${sid}/ai?market=${market}`, { method: "POST" });
    if (!r.ok) throw new Error(`Strategy AI failed: ${r.status}`);
    return r.json();
  },
  macroStrategyBacktestConfig: async (sid: string, market: "us" | "kr" = "kr"): Promise<StrategyBacktestConfig> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/strategy/${sid}/backtest-config?market=${market}`);
    if (!r.ok) throw new Error(`Strategy backtest-config failed: ${r.status}`);
    return r.json();
  },
  // 종목 단건 평가: 스크리너로 해당 종목을 찾아 가치평가 결과(intrinsic/gap/verdict + 펀더멘털) 반환
  companyLookup: async (universe: string, stockCode: string): Promise<ScreenerItem | null> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-advanced`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        universe,
        filter_ast: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }], groups: [] },
        limit: 200, liquidity_floor: "relaxed",
      }),
    });
    if (!r.ok) throw new Error(`Company lookup failed: ${r.status}`);
    const data = await r.json();
    return data.items.find((it: { stock_code: string }) => it.stock_code === stockCode) ?? null;
  },
  // 리스크: 스크리너 stress_test analyzer 재사용
  stressTest: async (universe: string, scenario: string): Promise<{
    analyzers: { stress_test?: { survival_rate: number; n_survivors: number; n_casualties: number; avg_shock_pct: number; casualties: Array<{ stock_code: string; corp_name: string; shock_pct: number; survived: boolean }>; scenario_label?: string } };
    data_source: { fundamentals: string; market_data: string; fully_real: boolean };
    total_passed: number;
  }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-advanced`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        universe,
        filter_ast: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }], groups: [] },
        limit: 30, liquidity_floor: "standard",
        analyzers: ["stress_test"], analyzer_params: { stress_test: { scenario } },
      }),
    });
    if (!r.ok) throw new Error(`Stress test failed: ${r.status}`);
    return r.json();
  },
  stressScenarios: async (): Promise<{ scenarios: Array<{ id: string; label: string }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/stress-scenarios`);
    if (!r.ok) throw new Error(`Scenarios failed: ${r.status}`);
    return r.json();
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// companyApi — Company Analysis 페이지 전용 단일종목 데이터 (실API 조립)
// ═══════════════════════════════════════════════════════════════════════════════
const POST = (path: string, body: unknown) =>
  fetch(`${API_BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
