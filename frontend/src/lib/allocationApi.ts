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

export interface AnalyzeRequest {
  tickers: string[];
  weights?: Record<string, number>;
  views?: AllocationViewInput[];
  model: AllocationModel;
  delta?: number;
  tau?: number;
  lookback_days?: number;
  benchmark?: string;
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

  stress: async (holdings: Record<string, number>, scenario: string): Promise<StressResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings, scenario }),
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
};
