// 기업 분석 "여러 모형"(BU6a+) — 백엔드에 이미 있는 가치 모형 여덟을 그대로 부른다.
// 라우트는 `src/api/company_routes.py`·`src/api/company_model_routes.py`(캔버스 노드가 같은 함수를 부른다).
// ★서버에 닿지 못하면 던진다(실패)★ · 서버가 `available:false` 로 답하면 그대로 돌려준다(못 함 + 사유) — 둘을 섞지 않는다.
// 가정형 셋(의사결정 나무·SOTP·실물옵션)은 여기 없다 — 기본값이 회사와 무관한 숫자라 이 화면에서 돌리지 않는다.

import { API_BASE, postJson } from "@/shared/api/apiBase";

/** 모형 응답의 공통 머리 — 모든 라우트가 싣는다. */
export interface ModelHead {
  available: boolean;
  reason?: string | null;
  is_mock?: boolean;
  note?: string | null;
}
/** 입력 하나 — basis 는 서버 어휘(관측·근사·가정·미상). */
export interface ModelInput { key: string; label: string; value: unknown; basis?: string; source?: string; unit?: string }

export interface ReverseDcf extends ModelHead {
  implied_growth_pct: number | null; current_growth_pct: number | null; gap_pp: number | null;
  current_growth_reason?: string | null; wacc_pct: number | null; base_dcf_price: number | null;
  implied_fcf_margin_pct?: { value_pct: number | null; note?: string } | null;
}
export interface Quant { available?: boolean; p10?: number | null; p25?: number | null; p50?: number | null; p75?: number | null; p90?: number | null; price_percentile?: number | null }
export interface ValuationDistribution extends ModelHead {
  unified: Quant; by_model: Record<string, Quant>;
  model_disagreement?: { spread_ratio?: number | null } | null;
  widths?: Record<string, { measured?: boolean } | string>;
  n_used?: number; n_requested?: number;
}
export interface MacroRow { shock: string; available: boolean; value_pct: number | null; value_won?: number | null; channel?: string; reason?: string | null }
export interface MacroSensitivity extends ModelHead {
  base_value?: number | null; rows: MacroRow[];
  asymmetry?: { ratio?: number | null; note?: string } | null;
  unavailable: { shock: string; target?: string; reason: string }[];
}
export interface EvaYear { year: string; available: boolean; roic: number | null; wacc: number | null; eva: number | null }
export interface Eva extends ModelHead {
  years: EvaYear[]; latest?: EvaYear | null;
  valuation?: { per_share: number | null; per_share_reason?: string | null } | null;
  value_driver?: { growth_creates_value?: boolean | null; per_share?: number | null } | null;
  inputs?: ModelInput[];
}
export interface ValueLayers extends ModelHead {
  layers: { key: string; label: string; per_share: number | null; reason?: string | null }[];
  full_per_share: number | null; weighted_per_share: number | null; weighted_reason?: string | null; franchise?: string | null;
  inputs?: ModelInput[];
}
export interface Multiples extends ModelHead {
  eps: number | null; per: number | null; peg: number | null; peg_reason?: string | null;
  justified?: { per: number | null; pbr: number | null; per_price: number | null; pbr_price: number | null; reason?: string | null } | null;
  peer?: { per_median: number | null; per_price: number | null } | null;
  inputs?: ModelInput[];
}
export interface DriverMc extends ModelHead {
  quantiles: Quant; histogram?: { counts: number[]; edges: number[] } | null;
  price_percentile: number | null; negative_share: number | null; deterministic_per_share?: number | null;
  inputs?: ModelInput[];
}
export interface ScenarioRow { name: string; prob: number; value: number | null; changed?: string[] }
export interface Scenarios extends ModelHead {
  rows: ScenarioRow[]; weighted: number | null; prob_above_price: number | null; inputs?: ModelInput[];
}

/**
 * 시나리오 가중의 경우 셋 — ★캔버스 노드 `company_scenarios` 의 기본값을 그대로 옮긴 것★
 * (`src/api/allocation_graph_nodes_company_models.py` ScenariosParams.scenarios). 사람이 정한 가정이라 화면은 "가정" 칩을 붙인다.
 * 서버 기본값이 바뀌면 `tests/test_insights_scenarios_mirror.py` 가 빨개진다(두 곳이 따로 놀지 않게).
 */
export const DEFAULT_SCENARIOS = [
  { name: "약세", prob: 0.25, g: 0.01, beta: 1.3 },
  { name: "기본", prob: 0.5 },
  { name: "강세", prob: 0.25, g: 0.03, beta: 0.9 },
] as const;

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await postJson(path, body);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
const co = (code: string) => `/api/v1/company/${encodeURIComponent(code)}`;

export const modelsApi = {
  reverseDcf: (code: string, price: number, marketCapEok: number | null) =>
    getJson<ReverseDcf>(`${co(code)}/reverse-dcf?price=${price}${marketCapEok != null ? `&market_cap=${marketCapEok}` : ""}`),
  distribution: (code: string, price: number) => getJson<ValuationDistribution>(`${co(code)}/valuation-distribution?price=${price}&n=2000`),
  macroSensitivity: (code: string, price: number) => getJson<MacroSensitivity>(`${co(code)}/macro-sensitivity?price=${price}&statistical=true`),
  eva: (code: string, price: number) => post<Eva>(`${co(code)}/models/eva`, { price }),
  valueLayers: (code: string, price: number) => post<ValueLayers>(`${co(code)}/models/value-layers`, { price }),
  multiples: (code: string, price: number) => post<Multiples>(`${co(code)}/models/multiples`, { price }),
  driverMc: (code: string, price: number) => post<DriverMc>(`${co(code)}/models/driver-mc`, { price }),
  scenarios: (code: string, price: number) => post<Scenarios>(`${co(code)}/models/scenarios`, { price, scenarios: DEFAULT_SCENARIOS }),
};
