/**
 * Narrative API Client — Phase 3 AI Intelligence
 * ==========================================================================
 * 6 domain narrative + streaming SSE + usage tracking.
 */

import { API_BASE } from "@/shared/api/apiBase";

// ─── Types ───────────────────────────────────────────────────────────────────

export type NarrativeDomain =
  | "stock" | "portfolio" | "macro" | "operations" | "counterfactual" | "daily";

export interface NarrativeResponse {
  content: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  cost_krw: number;
  elapsed_seconds: number;
  cached: boolean;
  error?: string | null;
  timestamp: string;
}

export interface UsageStats {
  configured: boolean;
  sdk_available: boolean;
  model: string;
  total_calls: number;
  total_cached: number;
  total_failures: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_cost_krw: number;
  by_model: Record<string, { calls: number; cost_usd: number }>;
  last_call_at?: string | null;
}

export interface DomainCatalog {
  domains: Array<{
    id: NarrativeDomain;
    name: string;
    description: string;
    endpoint: string;
  }>;
  streaming: string;
  model_default: string;
  differentiators: string[];
}

// ─── API ─────────────────────────────────────────────────────────────────────

export const narrativeApi = {
  // Stock analysis (Screener Item + ValuationDetail)
  stock: async (
    stockItem: Record<string, unknown>,
    valuationDetail: Record<string, unknown> = {},
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<NarrativeResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/stock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stock_item: stockItem,
        valuation_detail: valuationDetail,
        max_tokens: opts.maxTokens ?? 2000,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok) throw new Error(`Stock narrative failed: ${r.status}`);
    return r.json();
  },

  // Portfolio report (Backtest + Attribution)
  portfolio: async (
    backtestResult: Record<string, unknown>,
    attribution: Record<string, unknown> = {},
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<NarrativeResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        backtest_result: backtestResult,
        attribution,
        max_tokens: opts.maxTokens ?? 2500,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok) throw new Error(`Portfolio narrative failed: ${r.status}`);
    return r.json();
  },

  // Macro briefing
  macro: async (
    regimeState: Record<string, unknown>,
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<NarrativeResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/macro`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        regime_state: regimeState,
        max_tokens: opts.maxTokens ?? 2000,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok) throw new Error(`Macro narrative failed: ${r.status}`);
    return r.json();
  },

  // Operations analysis (Kill switch + Audit)
  operations: async (
    events: Array<Record<string, unknown>>,
    auditSummary: Record<string, unknown> = {},
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<NarrativeResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/operations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        events,
        audit_summary: auditSummary,
        max_tokens: opts.maxTokens ?? 2500,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok) throw new Error(`Operations narrative failed: ${r.status}`);
    return r.json();
  },

  // Counterfactual (What-If)
  counterfactual: async (
    actual: Record<string, unknown>,
    scenarios: Array<Record<string, unknown>>,
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<NarrativeResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/counterfactual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actual,
        scenarios,
        max_tokens: opts.maxTokens ?? 2500,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok) throw new Error(`Counterfactual narrative failed: ${r.status}`);
    return r.json();
  },

  // Daily summary
  daily: async (
    activities: Record<string, unknown>,
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<NarrativeResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/daily-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        activities,
        max_tokens: opts.maxTokens ?? 2000,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok) throw new Error(`Daily narrative failed: ${r.status}`);
    return r.json();
  },

  // SSE streaming for any domain
  stream: async (
    domain: NarrativeDomain,
    inputs: Record<string, unknown>,
    onChunk: (chunk: string) => void,
    opts: { maxTokens?: number; temperature?: number; model?: string } = {},
  ): Promise<void> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/stream/${domain}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        inputs,
        max_tokens: opts.maxTokens ?? 2500,
        temperature: opts.temperature ?? 0.3,
        model: opts.model,
      }),
    });
    if (!r.ok || !r.body) throw new Error(`Stream failed: ${r.status}`);

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          const data = JSON.parse(payload);
          if (data.chunk) onChunk(data.chunk);
          if (data.error) throw new Error(data.error);
          if (data.done) return;
        } catch (e) {
          if (e instanceof Error && e.message.includes("data")) {
            // JSON parse error — skip malformed
            continue;
          }
          throw e;
        }
      }
    }
  },

  // Usage stats
  usage: async (): Promise<UsageStats> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/usage`);
    if (!r.ok) throw new Error("Usage fetch failed");
    return r.json();
  },

  // Domain catalog
  domains: async (): Promise<DomainCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/domains`);
    if (!r.ok) throw new Error("Domains fetch failed");
    return r.json();
  },

  // Cache management
  cacheStats: async () => {
    const r = await fetch(`${API_BASE}/api/v1/narrative/cache/stats`);
    return r.ok ? r.json() : null;
  },

  cacheClear: async () => {
    await fetch(`${API_BASE}/api/v1/narrative/cache/clear`, { method: "POST" });
  },
};

// ─── Domain label maps ──────────────────────────────────────────────────────

export const DOMAIN_LABELS: Record<NarrativeDomain, string> = {
  stock:          "종목 분석",
  portfolio:      "포트폴리오 보고서",
  macro:          "매크로 브리핑",
  operations:     "운영 사건 분석",
  counterfactual: "What-If 시나리오",
  daily:          "일일 요약",
};

export const DOMAIN_COLORS: Record<NarrativeDomain, string> = {
  stock:          "#16a34a",
  portfolio:      "#1200ff",
  macro:          "#f97316",
  operations:     "#dc2626",
  counterfactual: "#8b5cf6",
  daily:          "#0891b2",
};

export const DOMAIN_DESCRIPTIONS: Record<NarrativeDomain, string> = {
  stock:          "RIM·DCF·DDM 가치평가 결과를 자연어로 해석합니다.",
  portfolio:      "백테스트 결과 + 5-Factor Attribution을 분석합니다.",
  macro:          "현재 시장 국면(Regime)과 5종 매크로 지표를 해석합니다.",
  operations:     "Kill switch 발동 / Drift 등 운영 사건을 사후 분석합니다.",
  counterfactual: "실제 결과와 N개 가상 시나리오를 비교해 의사결정의 가치를 정량화합니다.",
  daily:          "오늘의 모든 운영·시장·포지션 활동을 통합 요약합니다.",
};
