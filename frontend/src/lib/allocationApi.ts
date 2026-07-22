/**
 * Allocation Studio API Client
 * ==========================================================================
 * /api/v1/allocation/* — 포트폴리오 구축·최적화·분석 (Two Sigma Venn 벤치마킹)
 */

import { API_BASE } from "@/lib/apiBase";

// ─── Types ───────────────────────────────────────────────────────────────────

export type AllocationModel = "mvo" | "bl" | "risk_parity" | "hrp" | "min_var";

export interface AllocationViewInput {
  assets: string[];
  direction: 1 | -1;
  magnitude_pct: number;
  confidence: number; // 0~100
  label?: string;
}

export interface ConstraintsInput {
  max_weight_pct?: number | null;
  min_weight_pct?: number;
  group_caps_pct?: Record<string, number>;
  turnover_cap_pct?: number | null;
  beta_min?: number | null;
  beta_max?: number | null;
  cash_min_pct?: number;
  cash_max_pct?: number;
}

export interface ConstraintsReport {
  status: "ok" | "approx" | "infeasible";
  violations: { kind: string; detail: string; amount_pct?: number }[];
  binding: string[];
  relaxed: string[];
  notes: string[];
  reason?: string | null;
  projected?: boolean;
}

export interface AnalyzeRequest {
  tickers: string[];
  weights?: Record<string, number>;
  views?: AllocationViewInput[];
  model: AllocationModel;
  delta?: number;
  tau?: number;
  lookback_days?: number;
  benchmark?: string;
  constraints?: ConstraintsInput | null;   // P3 — 없으면 무제약(기존 동작)
  // ResearchRun 기록 (opt-in — 명시 요청 시에만 서버가 run_id 스탬프)
  record_run?: boolean;
  run_name?: string;
}

export interface FrontierPoint {
  return: number;       // 연 %
  volatility: number;   // 연 %
  sharpe: number;
  [wKey: string]: number; // w_{code} — 각 점의 자산별 가중치 %
}

export interface SummaryStats {
  expected_return_pct: number;
  volatility_pct: number;
  sharpe: number;
  max_drawdown_pct: number;
  sortino: number;
  calmar: number;
}

export interface AnalyzeResult {
  error: boolean;
  message?: string;
  names: string[];
  labels: Record<string, string>;
  excluded: { ticker: string; reason: string }[];
  coverage: { start: string | null; end: string | null; n_obs: number; benchmark_available: boolean; source?: "db" | "mock" };
  model: AllocationModel;
  params: { delta: number; tau: number; lookback_days: number };
  views_applied: boolean;
  skipped_views: unknown[];
  cap_missing: string[];
  weights: { current: Record<string, number>; optimized: Record<string, number> };
  flow: { market: Record<string, number>; view_applied: Record<string, number>; optimized: Record<string, number> };
  frontier: {
    curve: FrontierPoint[];
    cloud: { returns: number[]; volatilities: number[]; sharpes: number[] };
  };
  points: { current: PointRV; market: PointRV; optimal: PointRV };
  risk_contributions: Record<string, number>;
  correlation: Record<string, Record<string, number>>;
  summary: {
    portfolio: SummaryStats;
    benchmark: SummaryStats | null;
    active: Partial<SummaryStats> | null;
    benchmark_label: string | null;
    extra: { var_pct: number | null; cvar_pct: number | null; information_ratio: number | null };
  };
  mc: {
    bins: { x0: number; x1: number; count: number }[];
    expected_pct: number;
    var95_pct: number;
    cvar95_pct: number;
    note: string;
  };
  // P3 제약 엔진 — constraints 지정 시에만 존재
  constraints_report?: ConstraintsReport | null;
  // record_run=true 요청 시에만 존재 — null이면 DB 미가용(정직 보고)
  run_id?: string | null;
  run_recorded?: boolean;
}

export interface PointRV { return_pct: number; volatility_pct: number }

export interface XrayFactor {
  id: string;
  label: string;
  portfolio_z: number;
  benchmark_z: number;
  coverage_pct: number;
  n_universe: number;
}

export interface XrayResult {
  error: boolean;
  message?: string;
  factors: XrayFactor[];
  benchmark_label: string;
  note: string;
}

export interface StressScenarioMeta {
  id: string;
  label: string;
  description: string;
  mode: "hypothetical" | "historical";
  available: boolean;
  reason?: string;
}

export interface StressResult {
  error: boolean;
  message?: string;
  mode: "hypothetical" | "historical";
  available: boolean;
  scenario: string;
  label: string;
  reason?: string;
  // hypothetical
  severity?: number;
  portfolio_shock_pct?: number;
  rows?: { stock_code: string; corp_name: string; weight_pct: number; shock_pct: number; contribution_pct: number }[];
  note?: string;
  // historical
  dates?: string[];
  portfolio_dd?: number[];
  benchmark_dd?: number[];
  max_dd_pct?: number;
  benchmark_max_dd_pct?: number;
  total_return_pct?: number;
  benchmark_label?: string;
  dropped?: string[];
}

export interface SensitivityResult {
  error: boolean;
  message?: string;
  names: string[];
  labels: Record<string, string>;
  base_weights: number[];          // %
  matrix: number[][];              // 행=충격 자산, 열=반응 비중 Δ%p
  bump_pct: number;
  views_applied: boolean;
  excluded: { ticker: string; reason: string }[];
  coverage: { start: string | null; end: string | null; n_obs: number; source?: "db" | "mock" };
}

export interface SymbolHit { ticker: string; name: string; market?: string }

// ─── 팩터 기반 포트폴리오 ─────────────────────────────────────────────────────
export type FactorWeighting = "equal" | "factor_tilt" | "inverse_vol" | "risk_parity" | "min_var" | "hrp";

export interface FactorPortfolioInput {
  factors: { id: string; weight: number; direction?: number }[];
  tickers?: string[] | null;
  top_k: number;
  weighting: FactorWeighting;
  lookback_days?: number;
  sample_size?: number;
}

export interface FactorPortfolioResult {
  error: boolean;
  message?: string;
  holdings: { code: string; name: string; weight: number; score: number; coverage_pct: number }[];
  factors: { id: string; label: string; direction?: number; covered: boolean; n: number }[];
  weighting: string;
  candidates: number;
  ranked: number;
  note: string;
}

// ─── 카나리·마켓타이밍 ────────────────────────────────────────────────────────
export type CanarySignalType = "abs_mom" | "score_13612" | "ma_month" | "ma_day" | "threshold";

export interface CanaryInput {
  kind: "asset" | "indicator";
  id: string;
  signal: CanarySignalType;
  lookback: number;
  threshold: number;
  direction: "above" | "below";
}

export interface TimingInput {
  market: "kr" | "us";
  canaries: CanaryInput[];
  min_breadth: number;
  risk_on_assets: string[];
  risk_off_assets: string[];
  holdings?: Record<string, number> | null;
  overlay?: { type: "ma_day" | "abs_mom" | "none"; n?: number; lookback?: number };
}

export interface TimingAssetTrend {
  ticker: string; label: string; vs_ma200_pct: number | null; mom_12m: number | null;
  dist_52w_high: number | null; rsi: number | null; trend: string;
}

export interface TimingResult {
  error: boolean;
  message?: string;
  market: string;
  canary: {
    signal: "risk_on" | "risk_off"; hits: number; total: number; need: number;
    details: { kind: string; id: string; signal: string; label: string; value: number | null; pass: boolean }[];
  };
  holdings: { ticker: string; code: string; label: string; weight: number; in_trend: boolean; is_cash?: boolean }[];
  cash_pct: number;
  signal_label: string;
  overlay: string;
  market_timing: {
    composite: { score: number; label: string } | null;
    components: { key: string; label: string; value: number | null; score: number; weight: number }[] | null;
    assets: TimingAssetTrend[] | null;
  } | null;
}

// ─── 상관-국면 스트레스 ───────────────────────────────────────────────────────
export interface StressCorrInput {
  tickers: string[];
  weights?: Record<string, number>;
  lookback_days?: number;
  target_rho: number;
  intensity: number;
  confidence_level: number;
  portfolio_value?: number;
}

export interface StressCorrResult {
  error: boolean;
  message?: string;
  names: string[];
  labels: Record<string, string>;
  confidence_level: number;
  target_rho: number;
  intensity: number;
  base: { port_vol_pct: number; var_amount: number; component_var: Record<string, number> };
  stressed: { port_vol_pct: number; var_amount: number; component_var: Record<string, number> };
  delta_vol_pct: number | null;
  delta_var_pct: number | null;
  corr_shift: { from_avg_rho: number; to_avg_rho: number };
  excluded: { ticker: string; reason: string }[];
  coverage: { start: string | null; end: string | null; n_obs: number; source?: "db" | "mock" };
}

// ─── Client ──────────────────────────────────────────────────────────────────

export const allocationApi = {
  analyze: async (req: AnalyzeRequest): Promise<AnalyzeResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Allocation analyze failed: ${r.status}`);
    return r.json();
  },

  factorXray: async (holdings: Record<string, number>): Promise<XrayResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/factor-xray`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings }),
    });
    if (!r.ok) throw new Error(`Factor x-ray failed: ${r.status}`);
    return r.json();
  },

  stress: async (holdings: Record<string, number>, scenario: string, severity = 1.0): Promise<StressResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings, scenario, severity }),
    });
    if (!r.ok) throw new Error(`Stress failed: ${r.status}`);
    return r.json();
  },

  sensitivity: async (req: {
    tickers: string[]; views?: AllocationViewInput[]; delta?: number; tau?: number; bump_pct?: number;
  }): Promise<SensitivityResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/sensitivity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Sensitivity failed: ${r.status}`);
    return r.json();
  },

  stressCatalog: async (): Promise<{ scenarios: StressScenarioMeta[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress-catalog`);
    if (!r.ok) throw new Error(`Stress catalog failed: ${r.status}`);
    return r.json();
  },

  searchSymbols: async (q: string, limit = 12): Promise<SymbolHit[]> => {
    const r = await fetch(`${API_BASE}/api/v1/symbols/search?q=${encodeURIComponent(q)}&limit=${limit}`);
    if (!r.ok) throw new Error(`Symbol search failed: ${r.status}`);
    const j = await r.json();
    return (j.items || []) as SymbolHit[];
  },

  resolveNames: async (codes: string[]): Promise<Record<string, string>> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/resolve-names`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codes }),
    });
    if (!r.ok) throw new Error(`resolve-names failed: ${r.status}`);
    return ((await r.json()).labels || {}) as Record<string, string>;
  },

  factorPortfolio: async (req: FactorPortfolioInput): Promise<FactorPortfolioResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/factor-portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`factor-portfolio failed: ${r.status}`);
    return r.json();
  },

  timing: async (req: TimingInput): Promise<TimingResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`timing failed: ${r.status}`);
    return r.json();
  },

  stressCorrelation: async (req: StressCorrInput): Promise<StressCorrResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress-correlation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`stress-correlation failed: ${r.status}`);
    return r.json();
  },

  krScenarioCatalog: async (): Promise<{ scenarios: KrScenarioMeta[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/kr-scenario-catalog`);
    if (!r.ok) throw new Error(`kr-scenario-catalog failed: ${r.status}`);
    return r.json();
  },
  krScenario: async (req: { holdings: Record<string, number>; scenario: string; severity?: number;
    sleeves?: Record<string, string> | null }): Promise<KrScenarioResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/kr-scenario`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`kr-scenario failed: ${r.status}`);
    return r.json();
  },
};

// ── 국내 시나리오팩 (P3-b) ──
export interface KrScenarioMeta { id: string; label: string; description: string; source: string }
export interface KrScenarioResult {
  error: boolean;
  message?: string;
  scenario?: string;
  label?: string;
  description?: string;
  source?: string;
  severity?: number;
  portfolio_shock_pct?: number;
  market_shock_pct?: number;
  factor_attribution?: { factor: string; label: string; contribution_pct: number }[];
  rows?: { stock_code: string; corp_name: string; weight_pct: number; shock_pct: number; contribution_pct: number }[];
  most_vulnerable?: { stock_code: string; corp_name: string; shock_pct: number }[];
  sleeve_attribution?: { sleeve: string; contribution_pct: number }[] | null;
  assumptions?: { correlation_rise: number; volatility_rise: number; liquidity_deterioration: number; stressed_vol_pct: number };
  risk_proxy?: { var95_pct: number; cvar95_pct: number; mdd_proxy_pct: number };
  execution_feasibility?: string;
  hedge_note?: string;
  notes?: string[];
}
