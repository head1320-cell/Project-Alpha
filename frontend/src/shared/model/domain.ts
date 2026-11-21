// 여러 entity가 함께 쓰는 도메인 타입 (FSD shared kernel).
// entities 간 직접 참조(peer import)를 만들지 않으려고 여기로 내렸다 —
// 필터 AST는 screener·backtest·trading·data-quality가 모두 쓰고,
// ScreenerItem/ValuationDetail은 screener·company·macro·backtest가 함께 쓴다.

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

export interface ValuationDetail {
  ticker: string;
  corp_name: string;
  current_price: number;
  intrinsic_value: number;
  gap_pct: number;
  verdict: string;
  /** 서버가 연습용(mock) 재무로 계산했는지 — 화면의 연습용 칩이 함께 본다(BU6a+). */
  is_mock?: boolean;
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

export interface GraphRelations {
  supplier: Array<{ code: string; name: string }>;
  customer: Array<{ code: string; name: string }>;
  competitor: Array<{ code: string; name: string }>;
}

/**
 * 스크리너 응답의 데이터 축(`src/api/screener_routes.py::_detect_data_source`) — 반환한 줄 위의 집계.
 * ★`null` 은 '모른다'이지 합성이 아니다★ — 줄이 없거나 출처를 관측하지 못한 줄이 있으면 `null` 이고 `reason` 이 왜인지 말한다.
 * `fully_real === false` 만이 합성을 관측했다는 뜻이다. `mock_allowed` 는 설정(관측이 아니다).
 * 받는 곳: `/run-advanced`(캔버스 스크리너 노드) · `/screen-to-backtest`(저장 실행의 결과) · `/data-quality`.
 */
export interface ScreenerDataSource {
  /** `"dart_real"` · `"mock"` · `"mixed"` · `null`(모름). 택티컬 경로는 `"mock"` 고정 — 다른 생산자다. */
  fundamentals: string | null;
  /** `"kis_real"` · `"mock"` · `"mixed"` · `null`(모름). */
  market_data: string | null;
  fully_real: boolean | null;
  reason?: string | null;
  counts?: {
    fundamentals: { real: number; mock: number; missing: number; unknown: number };
    market_data: { real: number; mock: number; unknown: number };
  };
  mock_allowed?: boolean;
}
