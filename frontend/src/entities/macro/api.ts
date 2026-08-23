/**
 * Macro API Client — Phase 4
 * ==========================================================================
 */

import { API_BASE } from "@/shared/api/apiBase";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface MacroSeries {
  indicator: string;
  name: string;
  unit: string;
  source: "BOK" | "FRED" | "MOCK";
  timestamps: string[];
  values: number[];
  latest: number | null;
  prev: number | null;
  yoy: number | null;
  mom_pct: number | null;
  z_score: number | null;
  percentile: number | null;
  mean_5y: number | null;
  std_5y: number | null;
  trend: "up" | "down" | "flat";
  last_update?: string;
}

export interface MacroSnapshot {
  timestamp: string;
  series: Record<string, MacroSeries>;
  count: number;
}

export type Regime = "Goldilocks" | "Reflation" | "Stagflation" | "Disinflation";

export interface YieldCurvePoint {
  label: string;
  years: number;
  yield_pct: number;
  trend: string;
}

export interface AxisComponent {
  key: string; transform: "yoy" | "level"; sign: number; weight: number;
  z: number; z_mom: number | null; blend: number; contribution: number;
}
export interface AxisDetail { score: number; se: number; components: AxisComponent[] }

export interface RegimeState {
  timestamp: string;
  regime: Regime;
  growth_axis: number;
  inflation_axis: number;
  confidence: number;
  // v2: 축 분해(지표별 변환 z·기여 — 'CPI 레벨 σ vs 축' 표시 모순 해소) + 사분면 확률
  axis_detail?: { growth: AxisDetail; inflation: AxisDetail };
  regime_probs?: Record<string, number>;

  stress_score: number;
  stress_components: Record<string, number>;

  yield_curve: { points: YieldCurvePoint[]; spread_2y10y_bp: number | null };
  yield_inversion: boolean;
  inversion_severity: number | null;

  recommended_mode: "NORMAL" | "CAUTIOUS" | "DEFENSIVE";
  asset_tilts: Record<string, string>;
  description: string;

  dynamic_risk_free_rate: number | null;
  dynamic_kill_dd_threshold: number | null;

  market?: "kr" | "us";                                     // 분석 대상 시장
  markets?: { kr: RegimeState; us: RegimeState };           // KR/US 동시 (두 카드용)
}

// ─── 국면 앙상블 (A7) ────────────────────────────────────────────────────────
// `GET /macro/regime-ensemble` — 축 · 상태전환(Markov) · 군집(GMM) 세 도구를
// **나란히** 받는다. 평균내지 않는다: 어느 모형이 무슨 말을 했는지가 정보다.
//
// ★유니온으로 짜는 이유★ 미가용 도구에는 `probs` 자체가 없다(서버가 만들지 않는다).
// 옵셔널 필드로 두면 `tool.probs?.Goldilocks ?? 0` 이 컴파일되고, 그 순간 "추정하지
// 못했다" 가 "0%" 로 둔갑한다 — 이 저장소가 반복해서 고쳐 온 결함이다. `available`
// 로 좁히지 않으면 확률을 읽을 수 없게 타입이 막는다.
export interface RegimeToolUnavailable {
  available: false;
  reason: string;
}
export interface RegimeToolAvailable {
  available: true;
  method: "axis" | "markov" | "cluster";
  probs: Record<string, number>;
  argmax: Regime;
  detail: Record<string, unknown>;
  note: string;
}
export type RegimeTool = RegimeToolAvailable | RegimeToolUnavailable;

/** markov 가용일 때의 `detail` — 전이 그래프가 그리는 값. */
export interface MarkovDetail {
  k_regimes: number;
  n_obs: number;
  p_expansion: number;
  inflation_up: boolean;
  /**
   * ★열이 출발이다★ statsmodels 규약은 `P[j][i] = i → j` — 합이 1인 것은 행이 아니라
   * **열**이다(`test_transition_matrix_is_a_probability_matrix` 가 못박고 있다).
   * 방향이 필요하면 아래 `p_exp_to_con` / `p_con_to_exp` 를 쓰고 이 행렬을 직접
   * 인덱싱하지 말 것 — 뒤집어도 대각(지속성)은 같은 값이라 화면으로 티가 나지 않는다.
   */
  transition: number[][];
  expansion_state: number;
  /** 확장 상태 유지 확률(대각). */
  persistence: number;
  /** 확장 → 수축. 행렬에서 파생되지만 방향이 헷갈릴 수 없게 서버가 이름을 붙여 준다. */
  p_exp_to_con: number;
  /** 수축 → 확장. */
  p_con_to_exp: number;
}

export interface RegimeEnsemble {
  market: string;
  months: number;
  n_obs: number;
  regimes: Regime[];
  tools: { axis: RegimeTool; markov: RegimeTool; cluster: RegimeTool };
  agreement: { unanimous: boolean | null; picks: Record<string, Regime>; note: string };
  note: string;
}

// ─── 국면 설명·전환위험 (A8) ─────────────────────────────────────────────────
// `GET /macro/regime-explain` — A7 의 앙상블이 **결론**을 준다면 이쪽은 그 결론을
// 쓸 수 있게 만드는 것을 준다: 왜 그 국면인지(Shapley), 어디로 갈 위험이 있는지
// (Dirichlet 사후 전이), 역사적으로 어디쯤인지(월별 경로).

/** 리본 한 칸 = 한 달. */
export interface RegimePathPoint {
  t: string;
  growth: number;
  inflation: number;
  regime: Regime;
}

/**
 * ★화면은 `requested` 가 아니라 `n_months` 로 기간을 적어야 한다★
 * 요청 60개월에 실제 분류 가능한 달이 53개면 `truncated: true` 다. 요청값을 기간인
 * 것처럼 쓰면 없는 역사를 주장하게 된다 — 이 저장소의 매크로 시계열은 실측
 * 60개월뿐이고 "10년" 은 만들 수 없다.
 */
export interface RegimeSpan {
  first: string | null;
  last: string | null;
  n_months: number;
  requested: number;
  truncated: boolean;
  dropped_incomplete: number;
}

export interface TransitionRow {
  from: Regime;
  counts: number[];
  n: number;
  mean: Record<string, number>;
  ci90: Record<string, [number, number]>;
  expected_duration_months: number | null;
  /** 관측이 모자라 사전분포로 수축된 행. 값을 데이터인 척 쓰지 말 것. */
  shrunk: boolean;
  reason: string | null;
}

export type RegimeForecast =
  | { available: false; reason: string }
  | {
      available: true; k: number; from: Regime; draws: number;
      mean: Record<string, number>;
      ci90: Record<string, [number, number]>;
      note: string;
    };

export type RegimeTransitions =
  | { available: false; reason: string; span: RegimeSpan; path: RegimePathPoint[] }
  | {
      available: true;
      market: string;
      span: RegimeSpan;
      path: RegimePathPoint[];
      current: Regime;
      run_length_months: number;
      occupancy: Record<string, number>;
      regimes: Regime[];
      rows: TransitionRow[];
      n_transitions: number;
      forecast: RegimeForecast;
      prior: { alpha_diag: number; alpha_off: number; note: string };
      note: string;
    };

export interface DriverItem {
  key: string;
  label: string;
  axis: "growth" | "inflation";
  /** 지표 → 축. 정확 가법(항등식). */
  axis_contribution: number;
  /** 지표 → 확률. 정확 Shapley. 축 기여와 **부호가 다를 수 있다**. */
  phi: number;
}

export type RegimeDrivers =
  | { available: false; reason: string }
  | {
      available: true;
      market: string;
      regime: Regime;
      probability: number;
      baseline: number;
      drivers: DriverItem[];
      sum_phi: number;
      /** 효율성 공리의 잔차. 0 이 아니면 화면이 스스로 틀렸다고 말해야 한다. */
      efficiency_residual: number;
      axes: {
        growth: { score: number; se: number; components: AxisComponent[] };
        inflation: { score: number; se: number; components: AxisComponent[] };
      };
      n_features: number;
      n_coalitions: number;
      method: string;
      note: string;
    };

export interface RegimeExplain {
  market: string;
  transitions: RegimeTransitions;
  drivers: RegimeDrivers;
  span: RegimeSpan;
}

export interface HeatmapRow {
  indicator: string;
  name: string;
  unit: string;
  source: string;
  latest: number | null;
  mom_pct: number | null;
  yoy: number | null;
  z_score: number | null;
  percentile: number | null;
  trend: string;
}

// ─── API ─────────────────────────────────────────────────────────────────────

export const macroApi = {
  snapshot: async (useCache = true): Promise<MacroSnapshot> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/snapshot?use_cache=${useCache}`);
    if (!r.ok) throw new Error(`Snapshot failed: ${r.status}`);
    return r.json();
  },

  regime: async (): Promise<RegimeState> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/regime`);
    if (!r.ok) throw new Error(`Regime failed: ${r.status}`);
    return r.json();
  },

  regimeEnsemble: async (market = "kr", months = 60): Promise<RegimeEnsemble> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/regime-ensemble?market=${market}&months=${months}`);
    if (!r.ok) throw new Error(`Regime ensemble failed: ${r.status}`);
    return r.json();
  },

  regimeExplain: async (market = "kr", months = 60, forecastK = 3,
                        regime?: string): Promise<RegimeExplain> => {
    const q = new URLSearchParams({ market, months: String(months), forecast_k: String(forecastK) });
    if (regime) q.set("regime", regime);
    const r = await fetch(`${API_BASE}/api/v1/macro/regime-explain?${q}`);
    if (!r.ok) throw new Error(`Regime explain failed: ${r.status}`);
    return r.json();
  },

  yieldCurve: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/yield-curve`);
    if (!r.ok) throw new Error(`Yield curve failed: ${r.status}`);
    return r.json();
  },

  stress: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/stress`);
    if (!r.ok) throw new Error(`Stress failed: ${r.status}`);
    return r.json();
  },

  heatmap: async (): Promise<{ indicators: HeatmapRow[]; count: number; timestamp: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/heatmap`);
    if (!r.ok) throw new Error(`Heatmap failed: ${r.status}`);
    return r.json();
  },

  series: async (indicator: string): Promise<MacroSeries> => {
    const r = await fetch(`${API_BASE}/api/v1/macro/series/${indicator}`);
    if (!r.ok) throw new Error(`Series failed: ${r.status}`);
    return r.json();
  },

  dynamicParams: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/dynamic-params`);
    if (!r.ok) throw new Error(`Dynamic params failed: ${r.status}`);
    return r.json();
  },

  refresh: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/refresh`, { method: "POST" });
    if (!r.ok) throw new Error("Refresh failed");
    return r.json();
  },

  health: async () => {
    const r = await fetch(`${API_BASE}/api/v1/macro/health`);
    return r.ok ? r.json() : null;
  },
};

// ─── Style helpers ──────────────────────────────────────────────────────────

// ★하드코딩 hex 를 토큰으로 (A4-X2)★
// 이 두 스케일은 라이트 전용 값을 반환했다. 다크 스윕에서 `#1d4ed8` 이 zinc-950 위
// **2.64:1**, `#0891b2` 가 3.68:1, 국면 칩 배경 `#dcfce7` 는 다크에서도 연초록 그대로였다.
// 인라인 style 로 들어가므로 CSS 규칙으로는 덮을 수 없다 — 값 자체가 토큰이어야 한다.
// 라이트 값은 §52 에서 **한 글자도 바뀌지 않는다**. 다크 짝만 새로 생긴다.
// (§51 이 DONUT_COLORS 를 --cat-* 로 옮긴 것과 같은 기법이다.)
export const REGIME_COLORS: Record<Regime, { fg: string; bg: string; border: string }> = {
  Goldilocks:   { fg: "var(--rg-gold-fg)",  bg: "var(--rg-gold-bg)",  border: "var(--rg-gold-bd)" },
  Reflation:    { fg: "var(--rg-refl-fg)",  bg: "var(--rg-refl-bg)",  border: "var(--rg-refl-bd)" },
  Stagflation:  { fg: "var(--rg-stag-fg)",  bg: "var(--rg-stag-bg)",  border: "var(--rg-stag-bd)" },
  Disinflation: { fg: "var(--rg-disi-fg)",  bg: "var(--rg-disi-bg)",  border: "var(--rg-disi-bd)" },
};

export function zScoreColor(z: number | null): string {
  if (z == null) return "var(--z-none)";
  if (z > 2)  return "var(--z-vhigh)";   // 매우 높음
  if (z > 1)  return "var(--z-high)";    // 높음
  if (z > 0)  return "var(--z-up)";      // 약간 위
  if (z > -1) return "var(--z-down)";    // 약간 아래
  if (z > -2) return "var(--z-low)";     // 낮음
  return "var(--z-vlow)";                // 매우 낮음
}

export function trendIcon(trend: string): string {
  return trend === "up" ? "▲" : trend === "down" ? "▼" : "—";
}

export function trendColor(trend: string): string {
  // 상승/하락은 이미 토큰이 있다(§52 가 다크 짝을 정의). 세 번째 팔레트를 만들지 않는다.
  return trend === "up" ? "var(--color-bull)" : trend === "down" ? "var(--color-bear)" : "var(--z-none)";
}

export function stressColor(score: number): string {
  if (score >= 80) return "#7f1d1d";
  if (score >= 60) return "#dc2626";
  if (score >= 40) return "#f97316";
  if (score >= 20) return "#16a34a";
  return "#0891b2";
}
