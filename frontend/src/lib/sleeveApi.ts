/**
 * Neutralization · Sleeve Combination API Client (Full Expansion P3 잔여)
 * ==========================================================================
 * /api/v1/allocation/{neutralize,pair-spread,combine-sleeves,sleeve-analytics}
 */

import { API_BASE } from "@/lib/apiBase";

export interface NeutralizeResult {
  mode: string;
  weights: Record<string, number>;
  beta?: {
    error?: boolean; message?: string;
    weights?: Record<string, number>; target_beta?: number; achieved_beta?: number;
    beta_hit?: boolean; gross?: number; dollar_neutral?: boolean; long_only_feasible?: boolean; note?: string;
  };
  sector?: {
    error?: boolean; message?: string;
    sector_before_pct?: Record<string, number>; sector_after_pct?: Record<string, number>;
    target_pct?: Record<string, number>; max_deviation_pct?: number; neutral?: boolean; note?: string;
  };
}

export interface CombineResult {
  error: boolean; message?: string; method?: string;
  sleeve_allocation?: Record<string, number>;
  risk_contribution_pct?: Record<string, number>;
  sleeve_vol_pct?: Record<string, number>;
  combined_weights_pct?: Record<string, number>;
  n_sleeves?: number; n_stocks?: number; note?: string;
}

export interface SleeveAnalyticsResult {
  error: boolean; message?: string;
  sleeves?: string[];
  correlation?: Record<string, Record<string, number>>;
  clusters?: Record<string, number>;
  n_clusters?: number;
  risk_contribution_pct?: Record<string, number>;
  tail_dependency?: { lower_tail_coexceedance: number | null; interpretation?: string; basis: string };
  avg_correlation?: number;
  note?: string;
}

export interface SleeveInput { name: string; weights: Record<string, number> }

export const sleeveApi = {
  neutralize: async (req: { weights: Record<string, number>; mode: "beta" | "sector" | "both";
    target_beta?: number; dollar_neutral?: boolean; sector_target?: Record<string, number> | null }):
    Promise<NeutralizeResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/neutralize`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`neutralize failed: ${r.status}`);
    return r.json();
  },

  combineSleeves: async (req: { sleeves: SleeveInput[]; method: string;
    risk_budget?: Record<string, number> | null; scores?: Record<string, number> | null }):
    Promise<CombineResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/combine-sleeves`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`combine-sleeves failed: ${r.status}`);
    return r.json();
  },

  sleeveAnalytics: async (req: { sleeves: SleeveInput[]; weights?: Record<string, number> | null }):
    Promise<SleeveAnalyticsResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/sleeve-analytics`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`sleeve-analytics failed: ${r.status}`);
    return r.json();
  },
};
