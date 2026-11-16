/**
 * 분봉 백테스트 — 서버 응답의 모양 (`src/api/intraday_routes.py`).
 * ★값이 없으면 `null` 이다(0 이 아니다)★ — 운영 게이트가 막은 하루의 봉 수 · 수수료율을 모르는 실행의 비용 후 손익 ·
 * 거래일이 모자란 실행의 확률 · 기록하지 못한 시행 횟수. 사유는 서버가 문장으로 함께 준다.
 */
export type SourceCounts = { kis: number; synthetic: number; unknown: number };
export type SessionRules = {
  available: boolean; open: string | null; closing_auction_from: string | null; close: string | null;
  grade: string | null; reason: string | null; message: string | null;
};
/** 분봉만으로는 알 수 없는 것 — 답에 늘 실려 온다. */
export type UnknownNote = { what: string; label: string; reason: string; how_to_verify: string };

// ── 적재 범위 ───────────────────────────────────────────────────────────────

export type CoverageDay = {
  date: string; status: "loaded" | "blocked" | "unreadable" | "not_checked";
  tickers: number | null; bars: number | null; sources: SourceCounts | null; defect_total: number | null;
  session_shifted: boolean | null; blocked_rows: number; reason: string | null; message: string | null;
  by_ticker: Record<string, { bars: number; defect_total: number; first: string | null; last: string | null }>;
  missing_tickers: string[];
};
export type Coverage = {
  from: string; to: string; gate: { mock: boolean };
  days: CoverageDay[];
  summary: {
    calendar_days: number; loaded_days: number; blocked_days: number; unreadable_days: number; not_checked_days: number;
    bars: number; sources: SourceCounts; defect_total: number;
  };
  empty: { reason: string; message: string } | null;
  session_rules: SessionRules; unknowns: UnknownNote[]; limits: { days: number; tickers: number };
};

// ── 규칙 틀과 설정 칸 ───────────────────────────────────────────────────────

export type Choice = { value: string; label: string };
/** 고르는 칸(`choice`)에는 범위와 단위가 없다 — 서버가 그 열쇠를 싣지 않는다. */
export type FieldDef = {
  key: string; label: string; type: "int" | "float" | "time" | "choice";
  min?: number | null; max?: number | null; default: number | string | null; unit?: string; choices?: Choice[];
};
/** `custom`(직접 구성)은 매개변수 칸이 없고 조건 나무를 짓는다 — 전일 값이 필요한지는 조건에 따라 달라 `null` 이다. */
export type Template = {
  kind: string; label: string; summary: string; needs_prev: boolean | null; params: FieldDef[]; notes: string[]; custom: boolean;
};
export type Limits = {
  tickers: number; ticker_days: number; range_days: number; bytes: number;
  grid_cells: number; validate_work: number; folds_min: number; folds_max: number;
};
export type Templates = {
  templates: Template[]; grammar: Grammar; position: FieldDef[]; costs: FieldDef[]; limits: Limits;
  session_rules: SessionRules; unknowns: UnknownNote[]; gate: { mock: boolean };
};

// ── 직접 구성 — 조건 나무와 그 문법 (`src/engine/intraday/expr.py` · `rules.grammar()`) ─────────────────

/** 지표 잎 — 매개변수는 같은 층에 놓인다(`{"ind": "sma", "n": 20}`). 편집 중의 빈 칸은 `null`. */
export type IndNode = { ind: string } & { [param: string]: number | string | null };
export type ConstNode = { const: number | null };
/** 연산 마디. `op` 가 빈 글자면 아직 고르지 않은 것이다(편집 중에만). `bars` 는 '직전 M봉 동안' · 'N봉 전 값'의 봉 수, `from`·`to` 는 시각 창(HHMM). */
export type OpNode = { op: string; args: (Tree | null)[]; bars?: number | null; from?: string; to?: string };
export type Tree = IndNode | ConstNode | OpNode;

export type GrammarParam = { key: string; label: string; type: "int" | "float"; min: number; max: number; default: number; unit: string };
export type GrammarIndicator = { name: string; label: string; unit: string; needs_prev: boolean; params: GrammarParam[] };
export type GrammarOp = {
  name: string; label: string; symbol: string | null; gives: "bool" | "number"; args: ("bool" | "number")[];
  variadic: { kind: "bool" | "number"; min: number; max: number } | null;
  extra: { key: string; label: string; type: "int" | "time"; min?: number; max?: number; unit?: string }[];
};
/** 화면이 조건을 짓는 데 쓰는 표 — 지표 · 연산 · 이름표 · 범위는 전부 서버의 것이다(화면이 지어내지 않는다). */
export type Grammar = {
  slots: { key: "entry" | "entry_stop" | "exit"; label: string; kind: "bool" | "number" }[]; entry_rule: string;
  indicators: GrammarIndicator[]; ops: GrammarOp[]; units: Record<string, string>; limits: { nodes: number; depth: number };
};
/** `POST /intraday/rules/expand` 의 답 — 규칙을 나무로 풀고 검사한 것. 계산 · 기록은 없다. */
export type Expanded = {
  rule: { kind: "custom"; params: Record<string, Tree> }; source: { kind: string; label: string };
  text: string; nodes: number; depth: number; limits: { nodes: number; depth: number }; needs_prev: boolean; notes: string[];
};

// ── 실행 ────────────────────────────────────────────────────────────────────

export type Value = number | string | null;
export type SimulateRequest = {
  tickers: string[]; from: string; to: string;
  rule: { kind: string; params: Record<string, Value | Tree> };       // 직접 구성이면 값이 조건 나무다
  position: Record<string, Value>;
  costs: Record<string, Value>;
};
export type Grid = { folds: number; rule: Record<string, Value[]>; position: Record<string, Value[]> };
export type ValidateRequest = SimulateRequest & { walk_forward?: Grid };

export type Origin = { kind: string; sessions: SourceCounts; grade: "E0" | "E3" | null; grade_reason: string };
export type Skipped = { date: string; ticker: string; reason: string; message: string | null };
export type DataBlock = {
  days: number; sessions: number; bars: number; skipped: Skipped[]; skipped_total: number;
  skipped_by_reason: Record<string, number>; shifted_days: string[];
};
export type Assumption = { key: string; label: string; count: number };
export type Breakeven = { bp: number | null; turnover: number | null; spent_bp: number | null; reason: string | null };
/** 시행 기록의 답 — 기록하지 못했으면 수가 `null` 이고 사유가 붙는다(1 이 아니다). */
export type Trial = {
  recorded: boolean; new: boolean | null; runs: number | null; family_n: number | null; user_total: number | null;
  reason: string | null; message: string | null;
};
type Shared = {
  request: SimulateRequest & { walk_forward?: Grid };
  template: Template; session_rules: SessionRules; unknowns: UnknownNote[]; gate: { mock: boolean };
  empty: { reason: string; message: string } | null;
  data: DataBlock; origin: Origin | null; assumptions: Assumption[]; breakeven: Breakeven | null; trial: Trial | null;
};
/** 캔버스에서 실행해 남긴 결과의 목록 한 줄(`GET /intraday/results`) — 요약 자체는 노드가 읽는다. */
export type ResultRow = {
  trial_key: string; rule_kind: string | null; rule_label: string | null; rule_text: string | null; rule_text_reason: string | null;
  tickers: string[]; from: string; to: string;
  synthetic: boolean; grade_known: boolean; result_at: number; runs: number;
};
/** 못 읽으면 빈 목록이 아니라 `available: false` + 사유다. */
export type ResultList = { available: boolean; reason: string | null; results: ResultRow[] };
/** `J` 는 매매일지의 모양이다 — 서버가 같은 엔진으로 계산해 같은 모양으로 준다. 엔티티끼리 서로 참조하지 않으므로(FSD) 쓰는 위젯이 끼운다. */
export type Simulation<J = unknown> = Shared & { journal: J | null; events_by_kind: Record<string, number> };

// ── 괴리 — 올린 체결 ↔ 같은 규칙의 시뮬레이션 체결 ─────────────────────────────────

export type Side = "buy" | "sell";
/** 짝지은 것 하나. `adverse` 는 불리함(매수는 비싸게 · 매도는 싸게 체결된 만큼이 양수)이다. 하루 단위로 견줬으면 `minutes` 가 `null`. */
export type DivergencePair = {
  symbol: string; side: Side; date: string; sim_at: string; actual_at: string; minutes: number | null;
  sim_price: number; actual_price: number; adverse: number; ticks: number; bp: number;
  sim_quantity: number; actual_quantity: number; quantity_diff: number; parts: number;
};
export type DivergenceAlone = { symbol: string; side: Side; at: string; price: number; quantity: number; parts: number };
export type DivergenceStat = { won: number; ticks: number; bp: number };
/** 짝이 없으면 차이는 0 이 아니라 사유다. */
export type PriceGap =
  | { n: 0; reason: string; message: string }
  | { n: number; mean: DivergenceStat; median: DivergenceStat; worst: DivergencePair; adverse: number; favorable: number; even: number };
export type WindowRow = { minutes: number; matched: number; sim_only: number; actual_only: number; chosen: boolean };
export type DivergenceReport = {
  mode: "timed" | "daily"; degraded: { reason: string; message: string } | null; window_minutes: number;
  counts: { matched: number; sim_only: number; actual_only: number };
  by_window: WindowRow[];
  matched: DivergencePair[]; sim_only: DivergenceAlone[]; actual_only: DivergenceAlone[];
  price_gap: PriceGap;
  time_gap: { mean_minutes: number; median_minutes: number; max_minutes: number } | null;
  quantity_gap: { differs: number };
  set_aside: {
    rejected: { row: number; reason: string; message: string }[]; outside_period: number;
    other_symbols: { rows: number; symbols: string[] }; untimed: number;
  };
  inputs: { sim_fills: number; actual_rows: number; actual_fills: number };
  rejected_total: number; rows_limit: number;
};
export type PnlSide = { gross: number; net: number | null; trades: number };
/** 차이 = 실제 − 시뮬레이션. 한쪽의 비용을 모르면 비용 후 차이는 `null` + 사유다. */
export type PnlGap = {
  simulated: PnlSide; actual: PnlSide; gap: { gross: number; net: number | null };
  net_reason: string | null; net_message: string | null;
};
export type Divergence = {
  request: SimulateRequest; template: Template; gate: { mock: boolean };
  empty: { reason: string; message: string } | null;
  data: DataBlock; origin: Origin | null; trial: Trial | null;
  divergence: DivergenceReport | null; pnl: PnlGap | null;
};
/** 내가 돌린 분봉 백테스트의 설정 한 줄(`GET /intraday/trials`) — `request` 는 그대로 다시 보낼 수 있는 요청이다. */
export type TrialRow = {
  trial_key: string; rule_label: string | null; rule_text: string | null; rule_text_reason: string | null;
  runs: number; updated_at: number; request: SimulateRequest;
};
/** 못 읽으면 빈 목록이 아니라 `available: false` + 사유다. `unreadable` 은 설정이 깨져 싣지 못한 줄 수. */
export type TrialList = { available: boolean; reason: string | null; trials: TrialRow[]; unreadable: number };
/** `F` 는 매매일지의 체결 줄이다 — 엔티티끼리 서로 참조하지 않으므로(FSD) 쓰는 자리가 끼운다. */
export type DivergenceRequest<F = unknown> = SimulateRequest & { fills: F[]; window_minutes?: number };

// ── 판정 ────────────────────────────────────────────────────────────────────

/** 판정에 쓰는 요약 — 비용 전은 늘 있고, 비용 후는 모르면 `null`. */
export type Brief = {
  trades: number; gross_total: number; gross_expectancy: number | null;
  net_total: number | null; net_expectancy: number | null; win_rate: number | null; basis: "net" | "gross";
};
export type GateState = "ok" | "degraded" | "unknown";
export type Gate = { key: string; label: string; state: GateState; reason: string; facts: string[] };
export type GateTable = { gates: Gate[]; counts: Record<GateState, number>; sentence: string; on_synthetic: boolean };
export type OutOfSample = {
  split: {
    in_sample_days: number; out_of_sample_days: number; in_sample_from: string; in_sample_to: string;
    out_of_sample_from: string; out_of_sample_to: string; fraction: number;
  } | null;
  in_sample: Brief | null; out_of_sample: Brief | null; reason: string | null; views: number | null;
};
export type Multiplicity = {
  n: number; days: number | null; sharpe_per_day: number | null; psr0: number | null; dsr: number | null;
  dsr_effective: number | null; n_effective: number | null; n_effective_reason: string | null;
  corrected: boolean; unscored: number; value: number | null; threshold: number; reason: string | null; note: string;
};
export type WalkStep = {
  choose: { from: string; to: string }; apply: { from: string; to: string };
  candidates: (number | null)[]; chosen: number | null; chosen_expectancy: number | null; applied: Brief | null; reason: string | null;
};
export type WalkForward = {
  folds: number; steps: WalkStep[]; stitched: Brief | null; reason: string | null; message: string | null; note: string;
  cells: { index: number; rule: Record<string, Value>; position: Record<string, Value>; is_base: boolean; whole: Brief }[];
};
export type Validation = Shared & {
  summary: Brief | null;
  out_of_sample: OutOfSample | null;
  slippage: (Brief & { ticks: number; is_base: boolean })[];
  stress: { double: Brief; commission_bp: number | null; slippage_ticks: number } | null;
  walk_forward: WalkForward | null;
  multiplicity: Multiplicity | null;
  gates: GateTable | null;
};
