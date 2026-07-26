// 스크리너 실행·유니버스·상세평가.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type { ScreenerResponse, ScreenerRunRequest, UniversesResponse } from "../model";
import type { ValuationDetail } from "@/shared/model";

// ─── API ─────────────────────────────────────────────────────────────────────

export const screenerApi = {
  run: async (req: ScreenerRunRequest): Promise<ScreenerResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Screener run failed: ${r.status}`);
    return r.json();
  },

  universes: async (): Promise<UniversesResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/universes`);
    if (!r.ok) throw new Error("Universes fetch failed");
    return r.json();
  },

  cacheStats: async () => {
    const r = await fetch(`${API_BASE}/api/v1/screener/cache/stats`);
    return r.ok ? r.json() : null;
  },

  cacheClear: async () => {
    await fetch(`${API_BASE}/api/v1/screener/cache/clear`, { method: "POST" });
  },

  // Single stock detailed evaluation
  evaluate: async (
    stockCode: string,
    currentPrice: number,
    opts: Partial<{ beta: number; projection_years: number }> = {},
  ): Promise<ValuationDetail> => {
    const r = await fetch(`${API_BASE}/api/v1/valuation/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stock_code: stockCode,
        current_price: currentPrice,
        beta: opts.beta ?? 1.0,
        projection_years: opts.projection_years ?? 10,
      }),
    });
    if (!r.ok) throw new Error(`Evaluation failed: ${r.status}`);
    return r.json();
  },
};

// ─── Verdict styling helpers ────────────────────────────────────────────────
