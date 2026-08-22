// 매크로/분석 탭 도메인 모델 — 국면·전략·추천·상관·타이밍·궤적·밸류에이션.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import type { YieldCurvePoint } from "./api";

export type { YieldCurvePoint };

// YieldCurvePoint는 ./api 가 정본 (SSOT) — 중복 정의 제거
export interface MacroRegime {
  timestamp: string;
  regime: string;
  growth_axis: number;
  inflation_axis: number;
  confidence: number;
  stress_score: number;
  yield_curve: { spread_2y10y_bp?: number; points?: YieldCurvePoint[] } | null;
  yield_inversion: boolean;
  inversion_severity: number | null;
  recommended_mode: string;
  asset_tilts: Record<string, number | string>;
  description: string;
  stress_components?: Record<string, number>;
  dynamic_risk_free_rate?: number;
  dynamic_kill_dd_threshold?: number;
}

// ── Macro Cockpit 추가 타입 (전략·추천·대시보드·밸류) ──
export interface TacticalHolding { ticker: string; label: string; us_ticker: string; us_label: string; weight: number }
export interface TacticalStrategy { id: string; name: string; description: string; signal: string; family?: string; holdings: TacticalHolding[] }
export interface MacroStrategies { market: string; as_of: string; strategies: TacticalStrategy[] }
export interface RecommendRankItem { id: string; name: string; composite: number; fit_score: number; recent_return_12m: number | null; archetype_kr: string; signal: string }
export interface MacroRecommend {
  market: string; as_of: string;
  confidence: number;            // 0~1, 국면 분류 신뢰도
  low_conviction: boolean;       // confidence < 0.35
  data_lag_note: string;         // 매크로 지표 후행성 안내
  regime: { quadrant: string; quadrant_kr: string; stress: number; cycle: string; confidence: number };
  top: {
    id: string; name: string; signal: string; fit_score: number; composite: number;
    holdings: TacticalHolding[];         // 원 전략 배분(랭킹 계산 기준)
    holdings_final: TacticalHolding[];   // 신뢰도 오버레이 적용 — 화면 표시용
    cash_overlay_pct: number;            // holdings_final 중 현금성(BIL) 비중
  };
  narrative: string; narrative_source: "rule" | "claude";
  ranking: RecommendRankItem[];
  // ── v2 (CIO 리팩토링) ──
  regime_probs?: Record<string, number>;   // 사분면 확률(합=1) — 정적 신뢰도% 대체
  macro_allocation?: MacroAllocation;      // 매크로 임베딩 4계절 배분 (1순위 추천)
}
export interface MacroAllocAttribution {
  ticker: string; label: string; base: number; growth: number; inflation: number;
  stress: number; final: number;
}
export interface MacroAllocBand { ticker: string; label: string; p10: number; p50: number; p90: number }
export interface MacroAllocation {
  holdings: TacticalHolding[];
  attribution: MacroAllocAttribution[];
  bands: MacroAllocBand[];
  inputs: { growth: number; inflation: number; stress: number; se_g: number; se_i: number };
  method: string; note: string;
}
export interface CbSentimentBank {
  available: boolean; score?: number; label?: string; hawkish_hits?: number;
  dovish_hits?: number; terms?: string[]; note?: string; source?: string;
}
export interface CbSentiment { as_of: string; banks: { fed?: CbSentimentBank; bok?: CbSentimentBank }; method: string }
export interface CausalEdge { from: string; to: string; from_label: string; to_label: string; lag: number; p: number }
export interface CausalGraph {
  available: boolean; nodes: { id: string; label: string }[]; edges: CausalEdge[];
  method?: string; note?: string;
}
// ── v3 시각화 (밸리AI 흡수) ──
export interface CycleStrips {
  market: string; months: string[]; note: string;
  indicators: { key: string; label: string; transform: string; cells: (number | null)[] }[];
}
export interface AxisHistory {
  market: string; note: string;
  points: { t: string; growth: number; inflation: number;
    growth_parts: Record<string, number>; inflation_parts: Record<string, number> }[];
}
export interface AssetStrips {
  market: string; months: number; note: string;
  assets: { ticker: string; label: string; cells: (number | null)[]; now: number | null }[];
}
export interface KrUsCompare {
  note: string;
  rows: { label: string; kr: number | null; us: number | null; gap: number | null }[];
}
export interface MacroIndicator { id: string; name: string; unit: string; latest: number | null; z_score: number | null; percentile: number | null; delta: number | null; spark: number[] }
export interface MacroTheme { key: string; label: string; indicators: MacroIndicator[] }
export interface MacroDashboard { as_of: string; themes: MacroTheme[]; sources: { fred: boolean; bok: boolean } }
export interface MacroValuation {
  assets: Array<{ key: string; label: string; z: number | null }>;
  kr_market: { n: number; per_median: number; pbr_median: number } | null;
  sources: { prices: boolean; fundamentals: boolean };
}

// ── 상관/타이밍/궤적 (macro_analytics) ──
export interface CorrPoint { t: string; corr: number }
export interface CorrPair { key: string; label: string; series: CorrPoint[] }
export interface MacroCorrelations {
  matrix: { tickers: string[]; labels: string[]; values: number[][] };
  pairs: CorrPair[];
  avg_corr: CorrPoint[];
  stock_bond_now: { corr: number | null; verdict: string };
  sources: { prices: boolean };
}
export interface TimingComponent { key: string; label: string; value: number | null; score: number; weight: number }
export interface TrendRow { ticker: string; label: string; vs_ma200_pct: number | null; mom_12m: number | null; dist_52w_high: number | null; rsi: number | null; trend: string }
export interface MacroTiming {
  composite: { score: number; label: string };
  components: TimingComponent[];
  history: Array<{ t: string; score: number }>;
  assets: TrendRow[];
  sources: { prices: boolean; fred: boolean };
}
export interface TrajectoryPoint { t: string; growth: number; inflation: number; quadrant: string }
export interface MacroTrajectory {
  path: TrajectoryPoint[];
  transitions: Array<{ t: string; from: string; to: string }>;
  sources: { fred: boolean; bok: boolean };
}

// ── 전략 상세 (strategy_profiles) ──
export interface StrategyReference { authors: string; year: string; title: string; venue?: string }
export interface StrategyProfile {
  concept: string; mechanism: string[]; rationale: string; regime_note: string;
  params: Record<string, string>; references: StrategyReference[];
}
export interface RegimeFit { quadrant: string; quadrant_kr: string; fit: number }
export interface PerfPoint { t: string; v: number }
export interface PerfSummary {
  total_return_pct: number; cagr_pct: number; mdd_pct: number; vol_pct: number; recent_12m_pct: number | null;
}
export interface StrategyDetail {
  id: string; name: string; family: string; signal: string; archetype: string; archetype_kr: string;
  holdings: TacticalHolding[]; profile: StrategyProfile; regime_fit: RegimeFit[];
  perf: { curve: PerfPoint[]; summary: PerfSummary }; recent_return_12m: number | null;
  sources: { prices: boolean };
}
export interface StrategyAI { content: string; tokens: number; cost_krw: number; cached: boolean; error?: string | null }

// ── 전략 → 백테스터 셋업 구성 (하이브리드) ──
export interface StrategyBacktestConfig {
  id: string; name: string; family: string; market: string;
  mode: "conditions" | "asset_alloc" | "engine"; note: string;
  // conditions
  universe_codes?: string[];
  buy_conditions?: Array<{ expr: string; op?: string; rhs?: number }>;
  buy_logic?: string | null;
  sort_expr?: string | null;
  sort_desc?: boolean;
  max_tickers?: number;
  rebalance_period?: string;
  // asset_alloc
  basket?: Array<{ ticker: string; name: string; weight_pct: number }>;
  rebalance_months?: number;
  // engine
  engine_strategy?: string;
}

export interface ValuationResult {
  stock_code: string;
  corp_name?: string;
  current_price: number;
  intrinsic_value: number;
  gap_pct: number;
  verdict: string;
  models: Array<{ model: string; intrinsic_value: number; weight: number }>;
}
