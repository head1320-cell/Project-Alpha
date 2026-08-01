/**
 * Allocation Studio API Client
 * ==========================================================================
 * /api/v1/allocation/* — 포트폴리오 구축·최적화·분석 (Two Sigma Venn 벤치마킹)
 */

import { API_BASE } from "@/shared/api/apiBase";

// ─── Types ───────────────────────────────────────────────────────────────────

export type AllocationModel = "mvo" | "bl" | "risk_parity" | "hrp" | "min_var" | "max_div" | "min_cvar";

export interface AllocationViewInput {
  assets: string[];
  direction: 1 | -1;
  magnitude_pct: number;
  confidence: number; // 0~100
  label?: string;
}

export interface ConstraintsInput {
  max_weight_pct?: number | null;
  min_weight_pct?: number;
  group_caps_pct?: Record<string, number>;
  turnover_cap_pct?: number | null;
  beta_min?: number | null;
  beta_max?: number | null;
  cash_min_pct?: number;
  cash_max_pct?: number;
}

export interface ConstraintsReport {
  status: "ok" | "approx" | "infeasible";
  violations: { kind: string; detail: string; amount_pct?: number }[];
  binding: string[];
  relaxed: string[];
  notes: string[];
  reason?: string | null;
  projected?: boolean;
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
  constraints?: ConstraintsInput | null;   // P3 — 없으면 무제약(기존 동작)
  // ResearchRun 기록 (opt-in — 명시 요청 시에만 서버가 run_id 스탬프)
  record_run?: boolean;
  run_name?: string;
  /** 이 결정을 내릴 때 붙어 있던 매크로 국면 스냅샷 (Phase 4a — 서버가 런에 함께 스탬프) */
  regime_snapshot_id?: string | null;
  /**
   * 이 결정을 검증한 시나리오 팩 (Phase 10b — 서버가 런에 함께 스탬프).
   * ★해시는 보내지 않는다★ 서버가 지금 해석한 팩의 신원을 찍는다 — 클라이언트가 해시를
   * 주장할 수 있으면 실제로 쓰지 않은 팩 버전을 썼다고 적힌 런이 만들어진다.
   */
  scenario_pack_id?: string | null;
  /**
   * 이 결정에 쓰인 타이밍 룰셋의 신원 (Phase 7 — 서버가 런에 함께 스탬프).
   * 스냅샷과 짝을 이루는 재현 좌표다. 서버는 계산 **전에** 검증하고, 없는 조합이면 422 다.
   */
  timing_rule_set_id?: string | null;
  timing_rule_set_version?: number | null;
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
  enb?: { enb: number; neff: number; n_assets: number; note: string };
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
  // P3 제약 엔진 — constraints 지정 시에만 존재
  constraints_report?: ConstraintsReport | null;
  // record_run=true 요청 시에만 존재 — null이면 DB 미가용(정직 보고)
  run_id?: string | null;
  run_recorded?: boolean;
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

// ── 통합 시나리오 카탈로그 (스펙 §5 의 12 패밀리 · ScenarioPackV2) ──
//
// ★두 축을 한 타입으로 묶지 않는다★
// `family` 는 **분류**(§5 의 12종, 앞으로도 늘 수 있다)이고 `mode` 는 실행 엔진에서 온
// **고정 어휘**다. Phase 9 전에는 둘이 같은 유니온을 쓰고 있어서, 패밀리를 늘리는 순간
// 결과 렌더링 분기까지 함께 흔들렸다.
// `(string & {})` 트릭: 알려진 12개는 자동완성에 뜨면서도 새 패밀리가 추가될 때 타입을
// 고치지 않아도 된다. 그냥 `string` 이면 자동완성이 사라지고, 순수 유니온이면 백엔드가
// 패밀리를 하나 늘릴 때마다 프론트가 컴파일 에러로 막힌다 — 분류는 늘어나는 축이다.
export type KnownStressFamily =
  | "historical_replay" | "growth_inflation" | "correlation_hedge_failure"
  | "volatility_liquidity" | "credit_tightening" | "krw_foreign_flow"
  | "semiconductor_chain" | "valueup_unwind" | "earnings_dispersion"
  | "retail_deleveraging" | "shortsell_borrow" | "user_authored";
export type StressFamily = KnownStressFamily | (string & {});
export type StressMode = "hypothetical" | "historical" | "kr_pack";
/** 이 결과가 무엇인지에 대한 주장 — 분류와 **다른 축**이다(§5). */
export type StressModelType = "historical_replay" | "hypothetical";
export type StressEngine = "m8" | "hist_replay" | "kr_pack" | "inline";

/** 목록 배지용 짧은 라벨. 상세 패널에는 서버가 준 `model_type_label` 전문을 쓴다. */
export const MODEL_TYPE_SHORT: Record<StressModelType, string> = {
  historical_replay: "실제 시세",
  hypothetical: "가정",
};

export interface StressScenarioItem {
  id: string;
  pack_id: string;
  label: string;
  description: string;
  family: StressFamily;
  family_label: string;
  mode: StressMode;
  model_type: StressModelType;
  model_type_label: string;
  engine: StressEngine;
  content_hash: string;
  /** 재현 좌표 `pack_id@hash` — 계수가 바뀌면 함께 바뀐다. */
  identity: string;
  available: boolean;
  severity_applies: boolean;
  source: string;
  reason?: string;
}
export interface StressScenarioCatalog {
  groups: { family: StressFamily; label: string; items: StressScenarioItem[]; reason?: string }[];
  /** 팩이 없는 패밀리도 남는다 — `covered:false` + `reason`. */
  families: { id: StressFamily; label: string; count: number; covered: boolean; reason?: string }[];
  note: string;
}

// ── 시나리오 × 3자 비교 (Phase 9) ──
export interface ScenarioLeg {
  state: string;
  /** ★수치로 얻지 못하면 null★ NaN 을 0 이나 1 로 대체하지 않는다(백엔드와 같은 규칙). */
  exposure: number | null;
  method: string;
  on_count: number;
  off_count: number;
  unavailable_count: number;
  explanation: string;
  /** ★판정하지 못한 다리에는 없다★ 0 이 아니라 부재다. */
  shock_pct?: number | null;
  cash_pct?: number | null;
  /** 수치를 만들지 못한 사유 — 있으면 숫자 대신 이것을 보여준다. */
  reason?: string;
}
export interface ScenarioThreeWayResult {
  legs: Record<string, ScenarioLeg>;
  scenario: { shock_pct: number | null; shock_basis: string; label: string;
    available: boolean; reason?: string };
  pack: StressScenarioItem;
  model_type: StressModelType;
  identity: string;
  overlay: Record<string, unknown> | null;
  conflict: string | null;
  combination: string;
  composition_note: string;
  composed: boolean;
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
  severity?: number;
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

// ─── 팩터 기반 포트폴리오 ─────────────────────────────────────────────────────
export type FactorWeighting = "equal" | "factor_tilt" | "inverse_vol" | "risk_parity" | "min_var" | "hrp";

export interface FactorPortfolioInput {
  factors: { id: string; weight: number; direction?: number }[];
  tickers?: string[] | null;
  top_k: number;
  weighting: FactorWeighting;
  lookback_days?: number;
  sample_size?: number;
}

export interface FactorPortfolioResult {
  error: boolean;
  message?: string;
  holdings: { code: string; name: string; weight: number; score: number; coverage_pct: number }[];
  factors: { id: string; label: string; direction?: number; covered: boolean; n: number }[];
  weighting: string;
  candidates: number;
  ranked: number;
  note: string;
}

// ─── 카나리·마켓타이밍 ────────────────────────────────────────────────────────
// 기존 4종 + 신규 팩터 — 백엔드 timing_factors.CATALOG와 동일 id 체계(통합 팩터 창)
/**
 * 팩터 id. ★백엔드 `timing_factors.CATALOG` 가 단일 레지스트리다★
 *
 * 예전에는 여기에 id 를 나열했는데, 그 목록은 **이미 어긋나 있었다**(`curve_slope` 누락).
 * 게다가 `TimingFactorModal` 이 `f.id as CanarySignalType` 로 캐스팅하고 있어서 경계에서
 * 강제되지도 않았다 — 즉 두 번째 진실만 만들고 검사는 하지 않는 상태였다. CLAUDE.md 의
 * "개수는 세지 말고 레지스트리를 읽으세요" 를 그대로 적용해 목록을 두지 않는다.
 * 유효성은 백엔드가 판정한다(카탈로그에 없는 id 는 `read_factor` 가 unavailable + 사유).
 */
export type CanarySignalType = string;

export type TimingFamily =
  | "momentum" | "deviation" | "breakout" | "overnight" | "regime"
  // Phase 8 — 기존 5개에 들어맞지 않는 팩터군. regime 에 몰아넣으면 그 패밀리가
  // 잡동사니가 되어 패밀리 필터가 쓸모없어진다.
  | "breadth" | "volatility" | "drawdown" | "correlation";

export interface TimingFactorMeta {
  id: string;
  label: string;
  family: TimingFamily;
  params: Record<string, number>;
  default_threshold: number;
  default_direction: "above" | "below";
  unit: string;
  desc: string;
  provenance: string;
  existing: boolean;
  /** 이 팩터가 소비하는 데이터의 주기 — 리밸런싱 주기와 어긋나면 경고 대상(스펙 §8.1 13). */
  evaluation_frequency?: string;
  /**
   * ★as_of 시점이 필요한 팩터★ — 카나리 평가 경로(`evaluate(id, ticker, market, params)`)로는
   * 시점을 전달할 수 없어 **이 창에서 규칙으로 추가할 수 없다**. 추가를 허용하면 항상
   * 값이 없는(=위험-오프) 규칙이 조용히 만들어진다.
   */
  requires_as_of?: boolean;

  // ── §3.2 구조화 정의 필드 (Phase 12a) ──
  /** §6 분류. 자유 텍스트 `provenance` 를 **대체하지 않고** 필터·그룹용으로 함께 온다. */
  provenance_class?: "systrader_public" | "generic_public_technical"
                   | "institutional_public" | "user_defined";
  use_mode?: "gate" | "ranking" | "sizing" | "tilt" | "risk_off_trigger" | "scenario_trigger";
  /** 실제로 경계가 있는 단위에만 온다 — 없으면 null(추측한 상한을 넣지 않는다). */
  allowed_range?: [number, number] | null;
  release_lag?: string | null;
  revision_policy?: string | null;
  /**
   * 데이터 소스 자체의 가용성. `requires_as_of` 와 **직교한다** — 전자는 "소스가 없다",
   * 후자는 "이 창의 평가 경로로는 시점을 넘길 수 없다". 둘 다 추가를 막지만 사유가 다르다.
   */
  availability?: "available" | "partial" | "unavailable";
  unavailable_reason?: string | null;
  expected_failure_mode?: string;
}

export interface TimingFactorCatalog {
  groups: { family: TimingFamily; label: string; factors: TimingFactorMeta[] }[];
  families: { id: TimingFamily; label: string }[];
  schema: string[];
  note: string;
  /** 주기 등급표 — 백엔드가 내려준다. 프론트에 복제하면 두 진실이 생겨 조용히 어긋난다. */
  frequency_ranks?: Record<string, number>;
  rebalance_options?: { id: string; label: string }[];
}

/** 3-상태 시그널 — 결측은 위험-오프와 **다른 사실**이다(백엔드 SignalState 와 1:1). */
export type SignalStateValue = "risk_on" | "risk_off" | "unavailable";

export interface TimingFactorHistoryPoint {
  months_back: number;          // 0 = 현재
  value: number | null;         // null = 그 시점 값을 얻지 못했다(0 이 아니다)
  state: SignalStateValue;
}

export interface TimingFactorHistory {
  factor_id: string;
  ticker: string;
  market: string;
  threshold: number;
  direction: "above" | "below";
  step: string;                 // "month" — 표본 간격
  points: TimingFactorHistoryPoint[];   // 오래된 → 최신
  state_changes: number;
  available_count: number;
  unavailable_count: number;
  /** 이 미리보기가 무엇을 보여주지 못하는지 — 반드시 화면에 그대로 노출한다. */
  limitations: string[];
}

/** 3자 비교의 한 다리 — 백엔드 CompositeSignal 과 1:1. */
export interface ThreeWayLeg {
  state: SignalStateValue;
  exposure: number;             // 0.0~1.0
  method: string;
  on_count: number;
  off_count: number;
  unavailable_count: number;
  /** 왜 이 판정인지 — 스펙 §8 은 모든 위험-온/오프 판단에 이유를 요구한다. */
  explanation: string;
}

/**
 * 붙어 있는 국면 스냅샷에서 온 매크로 오버레이. **라이브 매크로가 아니다.**
 *
 * `usable=false` 는 "매크로가 중립" 이 아니라 **"매크로를 못 읽었다"** 다 — 둘을 같은
 * 화면으로 그리면 사용자는 매크로가 판단에 관여한 줄 안다.
 */
export interface ThreeWayOverlay {
  regime: string;
  recommended_mode: string;     // NORMAL | CAUTIOUS | DEFENSIVE
  confidence: number;           // 0.0~1.0
  stress_score: number;         // ★0~100 스케일★ 분수가 아니다
  data_status: string;
  research_usage: string;
  enabled: boolean;
  exposure_cap: number;
  usable: boolean;
}

export interface TimingThreeWay {
  legs: { baseline: ThreeWayLeg; timing_only: ThreeWayLeg; timing_macro: ThreeWayLeg };
  overlay: ThreeWayOverlay | null;   // null = 스냅샷이 안 붙었다(비교를 지어내지 않는다)
  conflict: string | null;
  factor_states: { factor_id: string; state: SignalStateValue }[];
  combination: string;
  as_of: string | null;
  regime_snapshot_id: string | null;
}

/** TimingRule 공통 스키마 — 팩터 + 실행/리스크 컨텍스트 (백엔드 dataclass와 1:1) */
export interface TimingRuleSpec {
  factor_id: string;
  universe?: string[];
  signal_family?: TimingFamily;
  observation_window?: Record<string, number>;
  entry_condition?: string;
  exit_condition?: string;
  risk_off_asset?: string[];
  rebalance_or_holding_period?: string;
  position_sizing?: string;
  leverage_cap?: number;
  transaction_cost_and_slippage?: { cost_bps: number; slippage_bps: number };
  point_in_time_data_timestamp?: string | null;
  params?: Record<string, number>;
  label?: string;
  /**
   * 사용자가 고른 임계. 생략하면 카탈로그 기본값.
   *
   * ★direction 은 일부러 없다★ 방향은 카탈로그만 아는 사실이다(`defense_first` 는 음수일 때
   * 위험-온) — 보낼 수 있게 두면 언젠가 반대로 보내 신호가 뒤집힌다.
   */
  threshold?: number | null;
}

export interface TimingRuleSet {
  set_id: string;
  name: string;
  market: string;
  rules: TimingRuleSpec[];
  gate: Record<string, unknown>;
  notes?: string | null;
  created_at?: number;
  updated_at?: number;
}

export interface CanaryInput {
  kind: "asset" | "indicator";
  id: string;
  signal: CanarySignalType;
  lookback: number;
  threshold: number;
  direction: "above" | "below";
  params?: Record<string, number>;      // 팩터별 파라미터(ma_days·k·days…)
  // ── TimingRule 공통 스키마(선택) — 지정 시 규칙 저장에 그대로 실림 ──
  universe?: string[];
  risk_off_asset?: string[];
  rebalance_or_holding_period?: string;
  position_sizing?: string;
  leverage_cap?: number;
}

export interface TimingInput {
  market: "kr" | "us";
  canaries: CanaryInput[];
  min_breadth: number;
  risk_on_assets: string[];
  risk_off_assets: string[];
  holdings?: Record<string, number> | null;
  overlay?: { type: "ma_day" | "abs_mom" | "none"; n?: number; lookback?: number };
  regime_blend?: boolean;
  target_vol_pct?: number | null;
}

export interface TimingAssetTrend {
  ticker: string; label: string; vs_ma200_pct: number | null; mom_12m: number | null;
  dist_52w_high: number | null; rsi: number | null; trend: string;
}

export interface TimingResult {
  error: boolean;
  message?: string;
  market: string;
  canary: {
    signal: "risk_on" | "risk_off"; hits: number; total: number; need: number;
    details: { kind: string; id: string; signal: string; label: string; value: number | null; pass: boolean }[];
  };
  holdings: { ticker: string; code: string; label: string; weight: number; in_trend: boolean; is_cash?: boolean }[];
  cash_pct: number;
  signal_label: string;
  overlay: string;
  regime_blend?: { probs: Record<string, number>; p_risk_on: number; note: string } | null;
  vol_target?: { target_pct: number; realized_pct: number; scale: number; cash_added_pct: number; note: string } | null;
  market_timing: {
    composite: { score: number; label: string } | null;
    components: { key: string; label: string; value: number | null; score: number; weight: number }[] | null;
    assets: TimingAssetTrend[] | null;
  } | null;
}

// ─── 상관-국면 스트레스 ───────────────────────────────────────────────────────
export interface StressCorrInput {
  tickers: string[];
  weights?: Record<string, number>;
  lookback_days?: number;
  target_rho: number;
  intensity: number;
  confidence_level: number;
  portfolio_value?: number;
}

export interface StressCorrResult {
  error: boolean;
  message?: string;
  names: string[];
  labels: Record<string, string>;
  confidence_level: number;
  target_rho: number;
  intensity: number;
  base: { port_vol_pct: number; var_amount: number; component_var: Record<string, number> };
  stressed: { port_vol_pct: number; var_amount: number; component_var: Record<string, number> };
  delta_vol_pct: number | null;
  delta_var_pct: number | null;
  corr_shift: { from_avg_rho: number; to_avg_rho: number };
  excluded: { ticker: string; reason: string }[];
  coverage: { start: string | null; end: string | null; n_obs: number; source?: "db" | "mock" };
}

// ─── Client ──────────────────────────────────────────────────────────────────

export interface BacktestInput {
  tickers: string[];
  model?: AllocationModel;
  views?: AllocationViewInput[];
  constraints?: ConstraintsInput | null;
  benchmark?: string;
  rebalance?: "M" | "Q";
  window_days?: number | null;      // null = expanding
  cost_bps?: number;
  lookback_days?: number;
  delta?: number;
  tau?: number;
}

export interface AllocationBacktestResult {
  error: boolean;
  message?: string;
  dates?: string[];
  equity_curve?: number[];
  bench_curve?: number[] | null;
  drawdown_curve?: number[];
  rebalances?: { date: string; weights: Record<string, number>; turnover_pct: number }[];
  n_rebalances?: number;
  turnover_avg_pct?: number;
  metrics?: Record<string, number | null>;
  summary?: {
    total_return_pct: number; cagr_pct: number; volatility_pct: number;
    sharpe_ratio: number; sortino_ratio: number; calmar_ratio: number; max_drawdown_pct: number;
    active_return_pct: number | null; information_ratio: number | null;
  };
  config?: { model: string; rebalance: string; window: string; cost_bps: number; n_obs: number };
  labels?: Record<string, string>;
  coverage?: { source?: string; start?: string; end?: string; n_obs?: number };
  benchmark_label?: string | null;
  excluded?: { ticker: string; reason: string }[];
}

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

  backtest: async (req: BacktestInput): Promise<AllocationBacktestResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Allocation backtest failed: ${r.status}`);
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

  stress: async (holdings: Record<string, number>, scenario: string, severity = 1.0): Promise<StressResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings, scenario, severity }),
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

  stressScenarios: async (): Promise<StressScenarioCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress-scenarios`);
    if (!r.ok) throw new Error(`stress-scenarios failed: ${r.status}`);
    return r.json();
  },

  scenarioThreeWay: async (req: {
    holdings: Record<string, number>; pack_id: string; severity?: number;
    market?: string; combination?: string; k?: number; weights?: number[];
    rules: Record<string, unknown>[]; regime_snapshot_id?: string | null;
    overlay_enabled?: boolean;
  }): Promise<ScenarioThreeWayResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/scenario-three-way`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`scenario-three-way failed: ${r.status}`);
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

  resolveNames: async (codes: string[]): Promise<Record<string, string>> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/resolve-names`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codes }),
    });
    if (!r.ok) throw new Error(`resolve-names failed: ${r.status}`);
    return ((await r.json()).labels || {}) as Record<string, string>;
  },

  factorPortfolio: async (req: FactorPortfolioInput): Promise<FactorPortfolioResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/factor-portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`factor-portfolio failed: ${r.status}`);
    return r.json();
  },

  /**
   * 팩터 과거 미리보기 (스펙 §8.1 요구 4).
   * 값을 만들 수 없어도 200 + limitations 로 온다 — 미리보기 불가는 요청 오류가 아니다.
   */
  timingFactorHistory: async (
    factorId: string,
    q: { ticker: string; market: string; months?: number; threshold?: number; direction?: string },
  ): Promise<TimingFactorHistory> => {
    const p = new URLSearchParams({ ticker: q.ticker, market: q.market });
    if (q.months != null) p.set("months", String(q.months));
    if (q.threshold != null) p.set("threshold", String(q.threshold));
    if (q.direction) p.set("direction", q.direction);
    const r = await fetch(
      `${API_BASE}/api/v1/allocation/timing-factors/${encodeURIComponent(factorId)}/history?${p}`);
    if (!r.ok) throw new Error(`timing-factor history failed: ${r.status}`);
    return r.json();
  },

  /**
   * 기준 vs 타이밍만 vs 타이밍+매크로 (스펙 §8).
   *
   * `regime_snapshot_id` 를 주지 않으면 세 번째 다리는 `unavailable` + 사유로 온다 —
   * 없는 비교를 그럴듯하게 채우지 않는다. `overlay_enabled=false` 면 오버레이는 판단에
   * 관여하지 않고 타이밍 단독과 같아진다(끌 수 있어야 "조용한 오버라이드" 가 아니다).
   */
  timingThreeWay: async (req: {
    market: string;
    combination: string;
    rules: TimingRuleSpec[];
    k?: number;
    weights?: number[];
    regime_snapshot_id?: string | null;
    overlay_enabled?: boolean;
    as_of?: string | null;
  }): Promise<TimingThreeWay> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing/three-way`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) {
      // 422 는 백엔드가 정직하게 거부한 것이다 — 사유를 삼키면 사용자가 원인을 알 수 없다.
      let why = `three-way failed: ${r.status}`;
      try { why = (await r.json()).detail || why; } catch { /* 본문이 JSON 이 아니면 상태만 */ }
      throw new Error(why);
    }
    return r.json();
  },

  timingFactors: async (): Promise<TimingFactorCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing-factors`);
    if (!r.ok) throw new Error(`timing-factors failed: ${r.status}`);
    return r.json();
  },

  saveTimingRules: async (req: {
    name: string; market: string; rules: TimingRuleSpec[];
    gate?: Record<string, unknown>; notes?: string | null; set_id?: string | null;
    // version 은 저장된 버전. 버전 열이 없는 DB 에서는 null 로 온다 — 1 로 지어내지 않는다.
  }): Promise<{ set_id: string; version: number | null; rules: TimingRuleSpec[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing-rules`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) {
      // 상태 코드만 던지면 "갱신할 룰셋이 없다"(고칠 수 있음)와 "저장소를 못 쓴다"(못 고침)가
      // 호출자에게 같은 것으로 보인다 — 서버가 구별해 보낸 사유를 삼키지 않는다.
      let why = `timing-rules save failed: ${r.status}`;
      try { why = (await r.json()).detail || why; } catch { /* 본문이 JSON 이 아니면 상태만 */ }
      throw new Error(why);
    }
    return r.json();
  },

  listTimingRules: async (): Promise<{ sets: TimingRuleSet[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing-rules`);
    if (!r.ok) throw new Error(`timing-rules list failed: ${r.status}`);
    return r.json();
  },

  /**
   * 룰셋 버전 이력. 런에 박힌 버전이 아직 실재하는지 확인하는 데 쓴다 —
   * 없으면 현재 버전으로 대신 보여주지 말고 "확인 불가"라고 적어야 한다.
   */
  timingRuleVersions: async (setId: string): Promise<{
    set_id: string; versions: { version: number; created_at: number; name: string }[];
  }> => {
    const r = await fetch(
      `${API_BASE}/api/v1/allocation/timing-rules/${encodeURIComponent(setId)}/versions`);
    if (!r.ok) throw new Error(`timing-rule versions failed: ${r.status}`);
    return r.json();
  },

  deleteTimingRules: async (setId: string): Promise<{ deleted: boolean }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing-rules/${setId}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`timing-rules delete failed: ${r.status}`);
    return r.json();
  },

  timing: async (req: TimingInput): Promise<TimingResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/timing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`timing failed: ${r.status}`);
    return r.json();
  },

  stressCorrelation: async (req: StressCorrInput): Promise<StressCorrResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/stress-correlation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`stress-correlation failed: ${r.status}`);
    return r.json();
  },

  krScenarioCatalog: async (): Promise<{ scenarios: KrScenarioMeta[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/kr-scenario-catalog`);
    if (!r.ok) throw new Error(`kr-scenario-catalog failed: ${r.status}`);
    return r.json();
  },
  krScenario: async (req: { holdings: Record<string, number>; scenario: string; severity?: number;
    sleeves?: Record<string, string> | null }): Promise<KrScenarioResult> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/kr-scenario`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`kr-scenario failed: ${r.status}`);
    return r.json();
  },
};

// ── 국내 시나리오팩 (P3-b) ──
export interface KrScenarioMeta { id: string; label: string; description: string; source: string }
export interface KrScenarioResult {
  error: boolean;
  message?: string;
  scenario?: string;
  label?: string;
  description?: string;
  source?: string;
  severity?: number;
  portfolio_shock_pct?: number;
  market_shock_pct?: number;
  factor_attribution?: { factor: string; label: string; contribution_pct: number }[];
  rows?: { stock_code: string; corp_name: string; weight_pct: number; shock_pct: number; contribution_pct: number }[];
  most_vulnerable?: { stock_code: string; corp_name: string; shock_pct: number }[];
  sleeve_attribution?: { sleeve: string; contribution_pct: number }[] | null;
  assumptions?: { correlation_rise: number; volatility_rise: number; liquidity_deterioration: number; stressed_vol_pct: number };
  risk_proxy?: { var95_pct: number; cvar95_pct: number; mdd_proxy_pct: number };
  execution_feasibility?: string;
  hedge_note?: string;
  notes?: string[];
}
