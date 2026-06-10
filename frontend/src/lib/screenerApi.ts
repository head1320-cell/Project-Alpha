/**
 * Screener API Client + Types
 * ==========================================================================
 * Wraps the backend /api/v1/screener/* endpoints with full TypeScript types.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export interface ScreenerItem {
  stock_code: string;
  corp_name: string;
  sector?: string | null;

  current_price: number;
  intrinsic_value: number;
  gap_pct: number;
  verdict: string;

  composite_score: number;
  gap_score: number;
  roe_score: number;
  stability_score: number;

  roe_pct?: number | null;
  roa_pct?: number | null;
  per?: number | null;
  pbr?: number | null;
  debt_ratio_pct?: number | null;
  dividend_yield_pct?: number | null;
  market_cap_억?: number | null;
  fcf_억?: number | null;

  rim_value?: number | null;
  dcf_value?: number | null;
  ddm_value?: number | null;
  // 동적 팩터 (펀더멘털 64 + 가격수급 28) — fieldId로 접근
  [key: string]: number | string | null | undefined;
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
}

export interface UniversesResponse {
  presets: Array<{ id: string; size: number; sample: string[] }>;
  filter_dimensions: string[];
  sort_fields: string[];
  scoring_formula: Record<string, string>;
  valuation_models: Record<string, string>;
}

// ─── Detailed evaluation (single stock) ──────────────────────────────────────

export interface ValuationDetail {
  ticker: string;
  corp_name: string;
  current_price: number;
  intrinsic_value: number;
  gap_pct: number;
  verdict: string;
  models: Array<{
    model: "RIM" | "DCF" | "DDM";
    intrinsic_value: number;
    available: boolean;
    error?: string | null;
    components: Record<string, number>;
    assumptions: Record<string, number>;
  }>;
  financial_summary: Record<string, number | null>;
  params: Record<string, unknown>;
}

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

export function verdictColor(verdict: string): {
  fg: string;
  bg: string;
  border: string;
} {
  if (verdict.includes("극심한 저평가"))
    return { fg: "#15803d", bg: "#dcfce7", border: "#86efac" };
  if (verdict.includes("저평가") && !verdict.includes("약간"))
    return { fg: "#16a34a", bg: "#f0fdf4", border: "#bbf7d0" };
  if (verdict === "약간 저평가")
    return { fg: "#65a30d", bg: "#f7fee7", border: "#d9f99d" };
  if (verdict === "적정")
    return { fg: "#525252", bg: "#fafafa", border: "#e5e5e5" };
  if (verdict === "약간 고평가")
    return { fg: "#ea580c", bg: "#fff7ed", border: "#fed7aa" };
  if (verdict.includes("극심한 고평가"))
    return { fg: "#b91c1c", bg: "#fef2f2", border: "#fecaca" };
  return { fg: "#dc2626", bg: "#fef2f2", border: "#fecaca" }; // 고평가
}

export function gapColor(gapPct: number): string {
  if (gapPct <= -30) return "#15803d";  // 짙은 녹색
  if (gapPct <= -15) return "#16a34a";
  if (gapPct <= -5)  return "#65a30d";
  if (gapPct <= 5)   return "#737373";  // 회색
  if (gapPct <= 15)  return "#ea580c";
  if (gapPct <= 30)  return "#dc2626";
  return "#b91c1c";                       // 짙은 빨강
}

export function formatKrw(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(1)}만`;
  return v.toLocaleString();
}

export function formatPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}


// ─── Milestone 1: Filter AST ──────────────────────────────────────────────────

export interface FilterConditionNode {
  field: string;
  op?: "lt" | "lte" | "gt" | "gte" | "eq" | "between";
  value?: number | null;
  value2?: number | null;
  rank_mode?: "top_pct" | "bottom_pct" | "top_n" | null;
  rank_value?: number | null;
  // V2 확장
  kind?: "field" | "formula" | "peer" | "technical" | "event" | "estimate" | "z_score" | "behavioral" | "graph" | "sentiment" | "vector_sim";
  formula?: string | null;
  peer_scope?: "sector" | "market" | null;
  peer_stat?: "mean" | "median" | "rank_pct" | null;
  indicator?: string | null;
  event_type?: string | null;
  within_days?: number | null;
  estimate_field?: string | null;
  z_field?: string | null;
  z_window?: number | null;
  behavior_signal?: string | null;
  graph_target?: string | null;
  graph_relation?: string | null;
  graph_depth?: number | null;
  sentiment_source?: string | null;
  vector_ticker?: string | null;
  vector_threshold?: number | null;
}

export interface FilterGroupNode {
  logic: "AND" | "OR";
  conditions: FilterConditionNode[];
  groups: FilterGroupNode[];
}

export interface FieldMeta {
  id: string;
  label: string;
  category: string;
  unit: string;
  higher_better: boolean;
  typical_min: number;
  typical_max: number;
}

export interface FieldsCatalog {
  categories: Array<{ id: string; label: string; fields: FieldMeta[] }>;
  operators: Array<{ id: string; label: string; name: string }>;
  rank_modes: Array<{ id: string; label: string; name: string }>;
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
export const screenerApiAdvanced = {
  fields: async (): Promise<FieldsCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fields`);
    if (!r.ok) throw new Error(`Fields fetch failed: ${r.status}`);
    return r.json();
  },

  runAdvanced: async (req: AdvancedRunRequest): Promise<ScreenerResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-advanced`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Advanced run failed: ${r.status}`);
    return r.json();
  },

  count: async (req: AdvancedRunRequest): Promise<{
    total_evaluated: number; total_passed: number; elapsed_seconds: number;
  }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/count`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Count failed: ${r.status}`);
    return r.json();
  },

  // 자연어 → 필터 AST 변환 (Claude + 키워드 룰 fallback)
  nl2ast: async (query: string): Promise<{
    ast: FilterGroupNode;
    explanation: string;
    confidence: number;
    source: "claude" | "mock";
    error: string | null;
  }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!r.ok) throw new Error(`NL2AST failed: ${r.status}`);
    return r.json();
  },

  nl2astExamples: async (): Promise<{ examples: string[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast/examples`);
    if (!r.ok) throw new Error(`Examples failed: ${r.status}`);
    return r.json();
  },

  // 기술적 지표 카탈로그 (RSI/MACD/볼린저 등 — 스크리너 technical 필터용)
  indicators: async (): Promise<TechnicalIndicatorCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/indicators`);
    if (!r.ok) throw new Error(`Indicators failed: ${r.status}`);
    return r.json();
  },
};

// 기술적 지표 카탈로그 타입
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
export function emptyFilterGroup(): FilterGroupNode {
  return { logic: "AND", conditions: [], groups: [] };
}

// Helper: 조건 라벨 생성 (UI 표시용)
export function conditionLabel(cond: FilterConditionNode, fieldLabel: string): string {
  if (cond.rank_mode === "top_pct") return `${fieldLabel} 상위 ${cond.rank_value}%`;
  if (cond.rank_mode === "bottom_pct") return `${fieldLabel} 하위 ${cond.rank_value}%`;
  if (cond.rank_mode === "top_n") return `${fieldLabel} 상위 ${cond.rank_value}종목`;
  const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=", between: "~" };
  if (cond.op === "between") return `${fieldLabel} ${cond.value}~${cond.value2}`;
  return `${fieldLabel} ${opMap[cond.op || "lt"]} ${cond.value}`;
}


// ─── Milestone 3: Macro-Adaptive Guidance ────────────────────────────────────

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

export async function fetchMacroGuidance(): Promise<MacroGuidance> {
  const r = await fetch(`${API_BASE}/api/v1/screener/macro-guidance`);
  if (!r.ok) throw new Error(`Macro guidance failed: ${r.status}`);
  return r.json();
}

// 추천 필터 → FilterConditionNode 변환
export function guidanceFilterToNode(f: MacroGuidance["recommended_filters"][0]): FilterConditionNode {
  if (f.rank_mode) {
    return {
      field: f.field,
      rank_mode: f.rank_mode as FilterConditionNode["rank_mode"],
      rank_value: f.rank_value ?? null,
    };
  }
  return {
    field: f.field,
    op: (f.op ?? "lt") as FilterConditionNode["op"],
    value: f.value ?? null,
  };
}


// ─── Milestone 4: Presets ─────────────────────────────────────────────────────

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

export const presetApi = {
  list: async (): Promise<PresetCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/presets`);
    if (!r.ok) throw new Error(`Presets fetch failed: ${r.status}`);
    return r.json();
  },
  detail: async (id: string): Promise<PresetDetail> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/presets/${id}`);
    if (!r.ok) throw new Error(`Preset detail failed: ${r.status}`);
    return r.json();
  },
  run: async (id: string, universe = "kospi50", limit = 50): Promise<ScreenerResponse & { preset_name: string; master: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/presets/${id}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ universe, limit }),
    });
    if (!r.ok) throw new Error(`Preset run failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V2 M1: Formula + Peer ───────────────────────────────────────────

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

export const screenerV2Api = {
  validateFormula: async (formula: string): Promise<FormulaValidation> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/validate-formula`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ formula }),
    });
    if (!r.ok) throw new Error(`Formula validation failed: ${r.status}`);
    return r.json();
  },
  peerGroups: async (universe = "kospi50"): Promise<PeerGroups> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/peer-groups?universe=${universe}`);
    if (!r.ok) throw new Error(`Peer groups failed: ${r.status}`);
    return r.json();
  },
};

// V2 조건 라벨 (수식/Peer 포함)
export function conditionLabelV2(cond: FilterConditionNode, fieldLabel: (id: string) => string): string {
  if (cond.kind === "sentiment") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    const srcMap: Record<string, string> = { news_score: "뉴스", call_tone: "콜 톤" };
    return `💬 ${srcMap[cond.sentiment_source || ""] || cond.sentiment_source} ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "vector_sim") {
    return `👯 ${cond.vector_ticker} 유사도 ≥ ${cond.vector_threshold}`;
  }
  if (cond.kind === "behavioral") {
    return `🧠 ${fieldLabel(cond.behavior_signal || "")}`;
  }
  if (cond.kind === "graph") {
    const relMap: Record<string, string> = { supplier: "공급사", customer: "고객사", competitor: "경쟁사" };
    return `🕸 ${cond.graph_target} ${relMap[cond.graph_relation || ""]} ${cond.graph_depth}-hop`;
  }
  if (cond.kind === "estimate") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    return `🔮 ${fieldLabel(cond.estimate_field || "")} ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "z_score") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    const win = cond.z_window ? `${Math.round(cond.z_window / 4)}년` : "";
    return `📉 ${fieldLabel(cond.z_field || "")} ${win} Z ${opMap[cond.op || "lt"]} ${cond.value}σ`;
  }
  if (cond.kind === "technical") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    return `📊 ${fieldLabel(cond.indicator || "")} ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "event") {
    return `📅 ${fieldLabel(cond.event_type || "")} ${cond.within_days}일 이내`;
  }
  if (cond.kind === "formula") {
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=", between: "~" };
    return `∑ (${cond.formula}) ${opMap[cond.op || "lt"]} ${cond.value}`;
  }
  if (cond.kind === "peer") {
    const scopeLabel = cond.peer_scope === "market" ? "전체" : "섹터";
    if (cond.peer_stat === "rank_pct") return `⚖ ${fieldLabel(cond.field)} ${scopeLabel} 상위 ${cond.rank_value}%`;
    const statLabel = cond.peer_stat === "median" ? "중앙값" : "평균";
    const opMap: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥" };
    return `⚖ ${fieldLabel(cond.field)} ${opMap[cond.op || "lt"]} ${scopeLabel} ${statLabel}`;
  }
  return conditionLabel(cond, fieldLabel(cond.field));
}


// ─── Screener V2 M2: NL2AST Copilot ───────────────────────────────────────────

export interface NL2ASTResult {
  ast: FilterGroupNode | null;
  explanation: string;
  confidence: number;
  source: "claude" | "mock" | "none";
  error: string | null;
}

export const copilotApi = {
  nl2ast: async (query: string): Promise<NL2ASTResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!r.ok) throw new Error(`NL2AST failed: ${r.status}`);
    return r.json();
  },
  examples: async (): Promise<{ examples: string[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast/examples`);
    if (!r.ok) throw new Error(`Examples failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V2 M3: Technical/Event ──────────────────────────────────────────

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

export const screenerV2DataApi = {
  indicators: async (): Promise<IndicatorCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/indicators`);
    if (!r.ok) throw new Error(`Indicators failed: ${r.status}`);
    return r.json();
  },
  eventsCatalog: async (): Promise<EventCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/events-catalog`);
    if (!r.ok) throw new Error(`Events catalog failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V2 M4: Point-in-Time ────────────────────────────────────────────

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

export const screenerPITApi = {
  dates: async (): Promise<PITDates> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/pit-dates`);
    if (!r.ok) throw new Error(`PIT dates failed: ${r.status}`);
    return r.json();
  },
  runPit: async (req: PITRunRequest): Promise<ScreenerResponse & { as_of_date: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-pit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || `PIT run failed: ${r.status}`);
    }
    return r.json();
  },
};


// ─── Screener V3 Phase 1: Estimates (M1) + Z-Score (M2) ───────────────────────

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

export const screenerV3Api = {
  estimatesCatalog: async (): Promise<EstimateCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/estimates-catalog`);
    if (!r.ok) throw new Error(`Estimates catalog failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V3 Phase 1.5: Liquidity Gate ────────────────────────────────────

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

export const liquidityApi = {
  profiles: async (): Promise<LiquidityProfiles> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/liquidity-profiles`);
    if (!r.ok) throw new Error(`Liquidity profiles failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V3 Phase 2: Behavioral (M3) + Graph (M4) ────────────────────────

export interface BehaviorSignals {
  signals: Array<{ id: string; label: string; description: string }>;
}
export interface GraphMeta {
  relations: Array<{ id: string; label: string; description: string }>;
  max_depth: number;
  nodes: Array<{ code: string; name: string }>;
}
export interface GraphRelations {
  supplier: Array<{ code: string; name: string }>;
  customer: Array<{ code: string; name: string }>;
  competitor: Array<{ code: string; name: string }>;
}

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

export interface SentimentCatalog {
  sources: Array<{ id: string; label: string; unit: string; typical_min: number; typical_max: number; description: string }>;
  note: string;
}
export interface VectorMeta {
  embed_dim: number;
  nodes: Array<{ code: string; name: string }>;
  note: string;
}

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

export const analyzerApi = {
  stressScenarios: async (): Promise<StressScenarios> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/stress-scenarios`);
    if (!r.ok) throw new Error(`Stress scenarios failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V3 Fundamental Factor Library (FFL) ─────────────────────────────

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

export const fundamentalsApi = {
  catalog: async (): Promise<FundamentalsCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fundamentals-catalog`);
    if (!r.ok) throw new Error(`Fundamentals catalog failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener → Backtester Bridge ─────────────────────────────────────────────

export interface BacktestStatistics {
  total_return_pct: number;
  cagr: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  max_drawdown_pct: number;
  num_trades: number;
  win_rate: number;
  profit_factor: number;
  avg_trade_return: number;
  total_commission: number;
  total_slippage: number;
}

export interface BacktestTrade {
  stock_code?: string;
  corp_name?: string;
  entry_date?: string;
  exit_date?: string;
  entry_price?: number;
  exit_price?: number;
  return_pct?: number;
  pnl?: number;
}

export interface MonthlyReturn {
  month: string;
  return_pct: number;
}

export interface ScreenToBacktestResult {
  error?: boolean;
  message?: string;
  screened_tickers: Array<{ stock_code: string; corp_name: string; composite_score: number | null }>;
  screened_count: number;
  backtest: {
    statistics: BacktestStatistics;
    equity_curve: number[];
    equity_dates: string[];
    drawdown_curve: number[];
    monthly_returns: Array<MonthlyReturn | number>;
    benchmark?: {
      label: string;
      curve: number[];
      total_return_pct: number;
      excess_return_pct: number;
      beta: number;
      alpha_pct: number;
    };
    trades: BacktestTrade[];
  };
  backtest_config: { strategy: string; period: string; initial_capital: number };
  data_source: { fundamentals: string; market_data: string; fully_real: boolean };
}

// 백테스트 고급 옵션 (수수료/슬리피지/손절/익절)
export interface BacktestAdvancedParams {
  commission_rate?: number;
  slippage_rate?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
}

export const backtestBridgeApi = {
// 커스텀 전략(BuilderState) 백테스트 — 빌더에서 만든 임의 전략 실행
  customBacktest: async (body: {
    universe: string; max_tickers: number;
    spec: unknown;  // BuilderState
    start_date: string; end_date: string; initial_capital: number;
  }): Promise<ScreenToBacktestResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/screen-to-backtest`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        universe: body.universe,
        filter_ast: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }], groups: [] },
        liquidity_floor: "standard",
        max_tickers: body.max_tickers,
        strategy_name: "__custom__",
        strategy_params: { spec: body.spec },
        start_date: body.start_date, end_date: body.end_date,
        initial_capital: body.initial_capital,
      }),
    });
    if (!r.ok) throw new Error(`Custom backtest failed: ${r.status}`);
    return r.json();
  },

  strategies: async (): Promise<{ strategies: Array<{ id: string; label: string }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/backtest-strategies`);
    if (!r.ok) throw new Error(`Strategies failed: ${r.status}`);
    return r.json();
  },
  screenToBacktest: async (body: {
    universe: string;
    custom_tickers?: string[] | null;
    filter_ast: FilterGroupNode;
    liquidity_floor: string;
    max_tickers: number;
    strategy_name: string;
    start_date: string;
    end_date: string;
    initial_capital?: number;
    commission_rate?: number;
    slippage_rate?: number;
    stop_loss_pct?: number | null;
    take_profit_pct?: number | null;
    max_positions?: number;
    buy_fill_type?: string;
    sell_fill_type?: string;
    max_hold_days?: number | null;
    min_hold_days?: number;
    sell_divide_pct?: number;
    max_sell_divisions?: number | null;
    buy_weight_mode?: string;
    buy_divide_pct?: number;
    max_buy_per_day?: number | null;
    max_buy_count?: number | null;
  }): Promise<ScreenToBacktestResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/screen-to-backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`Screen-to-backtest failed: ${r.status}`);
    return r.json();
  },

  fillPriceTypes: async (): Promise<{ groups: Array<{ id: string; label: string; types: Array<{ id: string; label: string }> }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fill-price-types`);
    if (!r.ok) throw new Error(`Fill price types failed: ${r.status}`);
    return r.json();
  },

  sectors: async (): Promise<{ sectors: Array<{ id: string; label: string; size: number; sample: string[] }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/sectors`);
    if (!r.ok) throw new Error(`Sectors failed: ${r.status}`);
    return r.json();
  },
};


// ─── Live Trading (자동매매) ──────────────────────────────────────────────────

export interface TradingMode {
  mode: "mock" | "paper" | "real";
  description: string;
  kis_use_mock: boolean;
  kis_is_paper: boolean;
  has_key: boolean;
}

export interface AccountStatus {
  mode: string;
  cash_krw: number;
  evaluated_total: number;
  stock_value: number;
  n_positions: number;
  positions: Array<{ ticker: string; name: string; quantity: number; avg_price: number; current_price: number; eval_amount: number; pnl_pct: number }>;
  safety: Record<string, unknown>;
}

export interface SafetyConfig {
  kill_switch: boolean;
  dry_run: boolean;
  max_position_pct: number;
  max_order_amount_krw: number;
  max_daily_invest_krw: number;
  max_positions: number;
  daily_loss_limit_pct: number;
  min_order_amount_krw: number;
  allow_duplicate_buy: boolean;
}

export interface TradeExecutionResult {
  mode: string;
  executed: Array<{ stock_code: string; stock_name: string; action: string; quantity: number; price: number; amount_krw: number; success: boolean; message: string }>;
  blocked: Array<{ stock_code: string; stock_name: string; blocked_by: string; amount_krw: number }>;
  summary: { n_signals: number; n_executed: number; n_blocked: number; daily_invested_krw: number; warnings: string[] };
  screened_tickers?: Array<{ stock_code: string; corp_name: string; composite_score: number | null }>;
  screened_count?: number;
}

const DEFAULT_SAFETY: SafetyConfig = {
  kill_switch: false, dry_run: true, max_position_pct: 0.20,
  max_order_amount_krw: 10_000_000, max_daily_invest_krw: 50_000_000,
  max_positions: 10, daily_loss_limit_pct: -5.0, min_order_amount_krw: 100_000,
  allow_duplicate_buy: false,
};

export const tradingApi = {
  mode: async (): Promise<TradingMode> => {
    const r = await fetch(`${API_BASE}/api/v1/trading/mode`);
    if (!r.ok) throw new Error(`Mode failed: ${r.status}`);
    return r.json();
  },
  status: async (): Promise<AccountStatus> => {
    const r = await fetch(`${API_BASE}/api/v1/trading/status`);
    if (!r.ok) throw new Error(`Status failed: ${r.status}`);
    return r.json();
  },
  screenToTrade: async (body: {
    universe: string; filter_ast: FilterGroupNode; liquidity_floor: string;
    max_tickers: number; action?: string; equal_weight?: boolean;
    safety?: Partial<SafetyConfig>;
  }): Promise<TradeExecutionResult> => {
    const r = await fetch(`${API_BASE}/api/v1/trading/screen-to-trade`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "buy", equal_weight: true, ...body,
        safety: { ...DEFAULT_SAFETY, ...(body.safety || {}) } }),
    });
    if (!r.ok) throw new Error(`Screen-to-trade failed: ${r.status}`);
    return r.json();
  },
};

export { DEFAULT_SAFETY };


// ─── Data Quality (데이터 인프라 QA) ──────────────────────────────────────────

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

// ─── Macro / Company / Risk (분석 탭) ─────────────────────────────────────────

export interface MacroRegime {
  timestamp: string;
  regime: string;
  growth_axis: number;
  inflation_axis: number;
  confidence: number;
  stress_score: number;
  yield_curve: { spread_2y10y_bp?: number } | null;
  yield_inversion: boolean;
  inversion_severity: number | null;
  recommended_mode: string;
  asset_tilts: Record<string, number>;
  description: string;
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

export const analysisApi = {
  macroRegime: async (): Promise<MacroRegime> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/regime`);
    if (!r.ok) throw new Error(`Macro regime failed: ${r.status}`);
    return r.json();
  },
  // 종목 단건 평가: 스크리너로 해당 종목을 찾아 가치평가 결과(intrinsic/gap/verdict + 펀더멘털) 반환
  companyLookup: async (universe: string, stockCode: string): Promise<import("@/lib/screenerApi").ScreenerItem | null> => {
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
