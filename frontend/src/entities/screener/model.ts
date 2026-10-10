import type { FilterGroupNode, ScreenerItem } from "@/shared/model/domain";
// 스크리너 도메인 모델 — 필터 AST · 카탈로그 · 응답 타입 (SSOT).
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ScreenerFilters {
  min_market_cap_억?: number | null;
  max_market_cap_억?: number | null;
  min_roe_pct?: number | null;
  max_roe_pct?: number | null;
  min_gap_pct?: number | null;
  max_gap_pct?: number | null;
  min_per?: number | null;
  max_per?: number | null;
  min_pbr?: number | null;
  max_pbr?: number | null;
  min_dividend_yield?: number | null;
  max_debt_ratio?: number | null;
  sectors?: string[] | null;
  require_positive_fcf?: boolean;
  verdicts?: string[] | null;
}

export interface ScreenerRunRequest {
  universe?: string;
  custom_tickers?: string[] | null;
  filters?: ScreenerFilters;
  sort_by?: string;
  ascending?: boolean;
  limit?: number;
  beta?: number;
  projection_years?: number;
  use_macro?: boolean;
  liquidity_floor?: string;
  analyzers?: string[];
  analyzer_params?: Record<string, unknown>;
}

export interface ScreenerResponse {
  universe: string;
  total_evaluated: number;
  total_passed: number;
  elapsed_seconds: number;
  cache_hits: number;
  cache_misses: number;
  failures: number;
  timestamp: string;
  items: ScreenerItem[];
  // 정직 카운터 (신규 — 옵셔널: 구버전 응답 호환)
  universe_size?: number;      // 마스터/프리셋 기준 유니버스 총원
  ingested_count?: number;     // 적재된 종목 수
  evaluated_actual?: number;   // 실제 산출 아이템 수 (게이트 전)
  capped?: boolean;            // 평가 상한(400) 발동
  liquidity_gate?: { before?: number; after?: number; filtered_out?: number };
}

export interface UniversesResponse {
  presets: Array<{ id: string; size: number; sample: string[] }>;
  filter_dimensions: string[];
  sort_fields: string[];
  scoring_formula: Record<string, string>;
  valuation_models: Record<string, string>;
}

// ─── Detailed evaluation (single stock) ──────────────────────────────────────

export interface TechnicalIndicatorMeta {
  id: string;
  label: string;
  category?: string;
  unit?: string;
  typical_min?: number;
  typical_max?: number;
}
export interface TechnicalIndicatorCatalog {
  categories: Array<{ id?: string; label: string; indicators: TechnicalIndicatorMeta[] }>;
}

// Helper: 빈 필터 그룹 생성

export interface MacroGuidance {
  regime: string;
  stress_score: number;
  recommended_mode: "NORMAL" | "CAUTIOUS" | "DEFENSIVE";
  description: string;
  guidance_text: string;
  recommended_filters: Array<{
    field: string;
    op?: string;
    value?: number;
    rank_mode?: string;
    rank_value?: number;
    label: string;
  }>;
  recommended_weights: { gap: number; roe: number; stability: number };
  asset_tilts: Record<string, string>;
  dynamic_risk_free_rate: number | null;
  timestamp: string;
}

export interface PresetItem {
  id: string;
  name: string;
  master: string;
  category: string;
  icon: string;
  description: string;
  use_macro: boolean;
  condition_count: number;
}

export interface PresetCatalog {
  categories: Array<{ id: string; label: string; presets: PresetItem[] }>;
  total: number;
}

export interface PresetDetail extends PresetItem {
  filter_ast: FilterGroupNode;
}

export interface FormulaValidation {
  valid: boolean;
  error: string | null;
  used_fields: string[];
}

export interface PeerGroups {
  scopes: Array<{
    id: string;
    label: string;
    groups: Array<{ name: string; count: number }>;
  }>;
  stats: Array<{ id: string; label: string }>;
}

export interface NL2ASTResult {
  ast: FilterGroupNode | null;
  explanation: string;
  confidence: number;
  source: "claude" | "mock" | "none";
  error: string | null;
}

export interface IndicatorMeta {
  id: string; label: string; unit: string;
  typical_min: number; typical_max: number; description: string;
}
export interface IndicatorCatalog {
  categories: Array<{ id: string; label: string; indicators: IndicatorMeta[] }>;
}
export interface EventCatalog {
  events: Array<{ id: string; label: string; description: string }>;
}

export interface PITDates {
  dates: string[];
  disclosure_lag_days: number;
  note: string;
}

export interface PITRunRequest {
  universe?: string;
  custom_tickers?: string[] | null;
  filter_ast: FilterGroupNode;
  as_of_date: string;
  sort_by?: string;
  limit?: number;
}

export interface EstimateCatalog {
  category: {
    id: string;
    label: string;
    fields: Array<{
      id: string; label: string; unit: string;
      typical_min: number; typical_max: number;
      higher_better: boolean; description: string;
    }>;
  };
}

export interface LiquidityProfiles {
  profiles: Array<{ id: string; label: string; description: string }>;
  default: string;
}

export interface LiquidityGateStats {
  applied: boolean;
  before: number;
  after: number;
  filtered_out: number;
  floor?: {
    min_adv_value_억: number;
    min_market_cap_억: number;
    max_spread_pct: number;
    require_tradable: boolean;
  };
}

export interface BehaviorSignals {
  signals: Array<{ id: string; label: string; description: string }>;
}
export interface GraphMeta {
  relations: Array<{ id: string; label: string; description: string }>;
  max_depth: number;
  nodes: Array<{ code: string; name: string }>;
}
export interface SentimentCatalog {
  sources: Array<{ id: string; label: string; unit: string; typical_min: number; typical_max: number; description: string }>;
  note: string;
}
export interface VectorMeta {
  embed_dim: number;
  nodes: Array<{ code: string; name: string }>;
  note: string;
}

export interface CollinearityResult {
  available: boolean;
  error?: string;
  n_stocks?: number;
  correlation?: { labels: string[]; matrix: number[][] };
  warnings?: string[];
  high_correlation_pairs?: Array<{ a: string; b: string; corr: number }>;
  style_concentration?: Record<string, number>;
  optimization?: {
    method: string;
    method_label: string;
    weights: Array<{ stock_code: string; corp_name: string; weight_pct: number; risk_score: number }>;
    effective_n: number;
    concentration_hhi: number;
    note: string;
  };
}

export interface StressTestResult {
  available: boolean;
  error?: string;
  scenario?: string;
  scenario_label?: string;
  n_stocks?: number;
  n_survivors?: number;
  n_casualties?: number;
  survival_rate?: number;
  avg_shock_pct?: number;
  casualties?: Array<{ stock_code: string; corp_name: string; base_score: number; shock_pct: number; stressed_score: number; survived: boolean }>;
  most_resilient?: Array<{ stock_code: string; corp_name: string; shock_pct: number }>;
  note?: string;
}

export interface StressScenarios {
  scenarios: Array<{ id: string; label: string; description: string; icon: string }>;
}

export interface FundamentalsCatalog {
  categories: Array<{
    id: string;
    label: string;
    factors: Array<{
      id: string; label: string; unit: string; higher_better: boolean;
      typical_min: number; typical_max: number; source: string; description: string;
    }>;
  }>;
  total: number;
}

export interface AdvancedRunRequest {
  universe?: string;
  custom_tickers?: string[] | null;
  filter_ast: FilterGroupNode;
  sort_by?: string;
  ascending?: boolean;
  limit?: number;
  beta?: number;
  projection_years?: number;
  use_macro?: boolean;
  liquidity_floor?: string;
  analyzers?: string[];
  analyzer_params?: Record<string, unknown>;
}

// Extend screenerApi with M1 methods
