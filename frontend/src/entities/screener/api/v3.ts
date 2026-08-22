// V3 — 추정치·유동성·행태·그래프·감성·벡터·애널라이저·펀더멘털.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type {
  FundamentalsCatalog,
  BehaviorSignals,
  EstimateCatalog,
  GraphMeta,
  LiquidityProfiles,
  SentimentCatalog,
  StressScenarios,
  VectorMeta,
} from "../model";

export const screenerV3Api = {
  estimatesCatalog: async (): Promise<EstimateCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/estimates-catalog`);
    if (!r.ok) throw new Error(`Estimates catalog failed: ${r.status}`);
    return r.json();
  },
};

// ─── Screener V3 Phase 1.5: Liquidity Gate ────────────────────────────────────

export const liquidityApi = {
  profiles: async (): Promise<LiquidityProfiles> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/liquidity-profiles`);
    if (!r.ok) throw new Error(`Liquidity profiles failed: ${r.status}`);
    return r.json();
  },
};

// ─── Screener V3 Phase 2: Behavioral (M3) + Graph (M4) ────────────────────────

export const behavioralApi = {
  signals: async (): Promise<BehaviorSignals> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/behavior-signals`);
    if (!r.ok) throw new Error(`Behavior signals failed: ${r.status}`);
    return r.json();
  },
};

export const graphApi = {
  meta: async (): Promise<GraphMeta> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/graph-meta`);
    if (!r.ok) throw new Error(`Graph meta failed: ${r.status}`);
    return r.json();
  },
  search: async (q: string): Promise<{ results: Array<{ code: string; name: string }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/graph-search?q=${encodeURIComponent(q)}`);
    if (!r.ok) throw new Error(`Graph search failed: ${r.status}`);
    return r.json();
  },
};

// ─── Screener V3 Phase 3: Sentiment (M5) + Vector (M6) ────────────────────────

export const sentimentApi = {
  catalog: async (): Promise<SentimentCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/sentiment-catalog`);
    if (!r.ok) throw new Error(`Sentiment catalog failed: ${r.status}`);
    return r.json();
  },
};
export const vectorApi = {
  meta: async (): Promise<VectorMeta> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/vector-meta`);
    if (!r.ok) throw new Error(`Vector meta failed: ${r.status}`);
    return r.json();
  },
};

// ─── Screener V3 Phase 4: Analyzers (M7 Collinearity + M8 Stress) ─────────────

export const analyzerApi = {
  stressScenarios: async (): Promise<StressScenarios> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/stress-scenarios`);
    if (!r.ok) throw new Error(`Stress scenarios failed: ${r.status}`);
    return r.json();
  },
};

// ─── Screener V3 Fundamental Factor Library (FFL) ─────────────────────────────

export const fundamentalsApi = {
  catalog: async (): Promise<FundamentalsCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fundamentals-catalog`);
    if (!r.ok) throw new Error(`Fundamentals catalog failed: ${r.status}`);
    return r.json();
  },
};

// ─── Screener → Backtester Bridge ─────────────────────────────────────────────
