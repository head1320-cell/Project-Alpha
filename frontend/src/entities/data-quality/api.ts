// 데이터 인프라 QA 리포트.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type { FilterGroupNode } from "@/shared/model";

export interface DataQualityReport {
  n_items: number;
  avg_score: number;
  health: "excellent" | "good" | "fair" | "poor" | "no_data";
  unknown_names: number;
  unknown_pct: number;
  issues_total: number;
  problem_items: Array<{ stock_code: string; corp_name: string; score: number; issues: string[]; missing: string[] }>;
  data_source: { fundamentals: string; market_data: string; fully_real: boolean };
}

export const dataQualityApi = {
  check: async (body: { universe: string; filter_ast: FilterGroupNode; liquidity_floor: string; limit: number }): Promise<DataQualityReport> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/data-quality`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`Data quality failed: ${r.status}`);
    return r.json();
  },
  masterStats: async (): Promise<{ builtin_stocks: number; sector_mapped: number; dart_cache_available: boolean; dart_cached_stocks: number; total_resolvable: number }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/stock-master/stats`);
    if (!r.ok) throw new Error(`Master stats failed: ${r.status}`);
    return r.json();
  },
};
