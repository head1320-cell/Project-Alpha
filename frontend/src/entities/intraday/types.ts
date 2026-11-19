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
  /** 실행 전 가설(G3)의 글자 수 상한 — 서버의 것(화면이 지어내지 않는다). */
  hypothesis_chars: number;
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

/** 수 칸 — 범위 · 출발값 · 단위는 서버의 문법 표의 것이다. 출발값이 `null` 이면 사용자가 정하는 칸이다(국면 수 · 국면 번호 — 비어서 시작). */
export type GrammarNumberParam = { key: string; label: string; type: "int" | "float"; min: number; max: number; default: number | null; unit: string };
/** 모형 칸 — 값은 내 모형의 열쇠(64자리 16진)다. 출발값이 없다(도구는 모형을 고르지 않는다). `kind` 는 어느 모형인지(지금은 `day_type`). */
export type GrammarModelParam = { key: string; label: string; type: "model"; kind: string };
/** 고르기 칸 — 보기 가운데 하나(지수 · K3). 출발값이 없다(도구는 지수를 고르지 않는다 — 비어서 시작). */
export type GrammarPickParam = { key: string; label: string; type: "pick"; choices: { value: string; label: string }[]; default: null };
export type GrammarParam = GrammarNumberParam | GrammarModelParam | GrammarPickParam;
/** `context` 는 그 지표가 세션 밖에서 받아야 하는 것(`day_types` — 하루 유형 모형 · `regimes` — 시장 국면) · 다른 지표는 `null`.
 *  `slots` 는 그 지표를 쓸 수 있는 규칙의 자리(시장 국면 확률은 진입 조건만) · `null`(옛 서버의 답이면 없음)이면 어디나. */
export type GrammarIndicator = {
  name: string; label: string; unit: string; needs_prev: boolean; params: GrammarParam[]; context: string | null;
  slots?: ("entry" | "entry_stop" | "exit")[] | null;
};
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
/** 실행 · 판정의 요청 — 실행 전 가설(G3)을 함께 보낼 수 있다(설정이 아니다 · 시행 열쇠에 들지 않는다). 괴리 보고의 요청은 받지 않는다. */
export type RunRequest = SimulateRequest & { hypothesis?: string };
export type ValidateRequest = RunRequest & { walk_forward?: Grid };

export type Origin = { kind: string; sessions: SourceCounts; grade: "E0" | "E3" | null; grade_reason: string };
export type Skipped = { date: string; ticker: string; reason: string; message: string | null };
export type DataBlock = {
  days: number; sessions: number; bars: number; skipped: Skipped[]; skipped_total: number;
  skipped_by_reason: Record<string, number>; shifted_days: string[];
};
export type Assumption = { key: string; label: string; count: number };
export type Breakeven = { bp: number | null; turnover: number | null; spent_bp: number | null; reason: string | null };
/** 실행 전 가설(G3) — 시행 줄에 처음 적은 것만 남는다. `at_run` 은 적을 때의 실행 횟수(1 = 첫 실행과 함께 · 결과를 보기 전).
 *  남기거나 읽지 못했으면 `text` · `at_run` · `before_results` 가 `null` 이고 `message` 가 그렇다고 말한다(가설이 없으면 줄 자체가 `null`). */
export type Hypothesis = { text: string | null; at_run: number | null; before_results: boolean | null; kept_now: boolean; message: string };
/** 시행 기록의 답 — 기록하지 못했으면 수가 `null` 이고 사유가 붙는다(1 이 아니다). */
export type Trial = {
  recorded: boolean;
  /** 이 실행이 남은 시행의 열쇠 — 국면별 나눔(K2)이 이것으로 묻는다. 기록하지 못했으면 `null`. */
  trial_key?: string | null;
  new: boolean | null; runs: number | null; family_n: number | null; user_total: number | null;
  reason: string | null; message: string | null;
  /** 실행 전 가설(G3) — 실행 · 판정의 시행 줄에만 있다(괴리 보고의 시행 줄 · G3 전에 남긴 결과에는 칸이 없다). */
  hypothesis?: Hypothesis | null;
};
/** 규칙이 쓴 하루 유형 모형 하나의 사실 줄(`src/api/intraday_context.facts`) — 문장은 서버의 것을 그대로 싣는다. 쓰지 않는 규칙이면 목록이 비어 있다.
 *  `kind` 가 없는 줄은 K3 전에 남긴 결과의 하루 유형 줄이다. */
export type DayTypeFact = {
  kind?: "day_type"; key: string; minutes: number; k: number; first_day: string; last_day: string; tickers: string[];
  grade: "E0" | "E3" | null; same_tickers: boolean; sentences: string[];
};
/** 규칙이 쓴 시장 국면 하나의 사실 줄(K3) — 아는 날 · 모르는 날 · 사유별 날 수 · 등급. 문장은 서버의 것 그대로. */
export type RegimeFact = {
  kind: "regime"; key: string; index: MarketIndex; name: string; k: number; states: number[]; grade: "E0" | "E3" | null;
  days: { loaded: number; known: number; unknown: number }; unknown_reasons: { reason: string; days: number }[]; sentences: string[];
};
export type ContextFact = DayTypeFact | RegimeFact;
/** 판정의 짝 비교(K3) — 같은 날 · 같은 포지션 · 같은 비용으로 국면 조건을 뺀 판. 시행으로 세지 않는다(판정의 일부). */
export type RegimePair = {
  known: boolean; reason: string | null; with: Brief | null; without: Brief | null; rule_text: string | null; note: string;
};
type Shared = {
  request: SimulateRequest & { walk_forward?: Grid };
  template: Template; session_rules: SessionRules; unknowns: UnknownNote[]; gate: { mock: boolean };
  empty: { reason: string; message: string } | null;
  data: DataBlock; origin: Origin | null; assumptions: Assumption[]; breakeven: Breakeven | null; trial: Trial | null;
  context: ContextFact[];
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
/** 순차 증거(부호 · G2) — 짝마다 불리 +1 · 유리 −1 · 같음 0 을 시뮬레이션 시각 순으로 쌓은 e-값(서버 `evalue.sign_evidence`).
 *  판정과 숫자의 글은 서버 문장(`message` · `basis` · `limit`)이다 — 화면은 고르기만 한다. 부호가 없으면 값은 `null` + `reason`. */
export type SignEvidence = {
  method: string; alpha: number; threshold: number; pairs: number; adverse: number; favorable: number; even: number;
  e_value: number | null; peak: number | null; saturated: boolean | null; passed: boolean | null; reason: string | null;
  question: string; message: string; basis: string; limit: string;
};
/** 짝이 없으면 차이는 0 이 아니라 사유다(순차 증거 블록도 없다). */
export type PriceGap =
  | { n: 0; reason: string; message: string }
  | { n: number; mean: DivergenceStat; median: DivergenceStat; worst: DivergencePair; adverse: number; favorable: number; even: number;
      sequential: SignEvidence };
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
  data: DataBlock; origin: Origin | null; trial: Trial | null; context: ContextFact[];
  divergence: DivergenceReport | null; pnl: PnlGap | null;
};
/** 내가 돌린 분봉 백테스트의 설정 한 줄(`GET /intraday/trials`) — `request` 는 그대로 다시 보낼 수 있는 요청이다. */
export type TrialRow = {
  trial_key: string; rule_label: string | null; rule_text: string | null; rule_text_reason: string | null;
  runs: number; updated_at: number; request: SimulateRequest;
  /** 실행 전 가설(G3) — 없으면 `null` · 읽지 못했으면 글이 `null` 인 줄(없음으로 꾸미지 않는다). 다시 보낼 `request` 에는 들지 않는다. */
  hypothesis: Hypothesis | null;
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
/** 순차 증거(e-값) — 다중 비교 관문의 ★사실 줄★로만 읽힌다(관문의 상태는 확률이 정한다). 값이 없으면 `reason`. */
export type Sequential = {
  method: string; alpha: number; trials: number; threshold: number; cap: number | null; days: number | null;
  e_value: number | null; peak: number | null; saturated: boolean | null; exceeded_days: number | null; worst: number | null;
  passed: boolean | null; reason: string | null; assumption: string | null; loss_limit: number | null; cap_multiple: number;
};
export type Multiplicity = {
  n: number; days: number | null; sharpe_per_day: number | null; psr0: number | null; dsr: number | null;
  dsr_effective: number | null; n_effective: number | null; n_effective_reason: string | null;
  corrected: boolean; unscored: number; value: number | null; threshold: number; reason: string | null; note: string;
  sequential: Sequential;
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
  /** 국면 조건을 쓴 규칙만 — 아니면 `null`(K3 전의 남긴 결과에는 칸이 없다). */
  regime_pair?: RegimePair | null;
  /** 자유도 공시(G3) — 빈 결과면 `null` · G3 전에 남긴 결과(캔버스)에는 칸이 없다. */
  freedom?: FreedomDisclosure | null;
};
/** 자유도 공시(G3 · `src/engine/intraday/freedom.disclose`) — 조정 가능한 값의 수와 이 실행의 거래 수. ★기술이며 기준이 아니다★(관문의 상태를 바꾸지 않는다).
 *  `per_value` 는 거래가 없거나 값이 없으면 `null`(나누지 않는다) · 문장은 서버의 것 그대로. */
export type FreedomDisclosure = {
  rule: number; rule_names: string[]; position: number; position_names: string[]; count: number;
  trades: number | null; per_value: number | null; question: string; message: string; basis: string; limit: string;
};

// ── 하루 유형 모형(T1 · 2026-11-16) — 장 시작 구간의 경로를 e-means 로 묶은 것. 서버 `intraday_day_type_routes` 의 답 그대로 ──
/** 유형 하나 — 번호는 구간 마지막 분의 값(bp)이 낮은 것부터. 흩어짐은 날이 없으면 `null`(미상). */
export type DayType = { type: number; samples: number; share: number; path: number[]; end: number; low: number; high: number; spread: number | null };
/** 같은 자료의 Lloyd 손실과 e-means 손실 — 보이는 글자와 문장은 서버가 짓는다(다시 반올림하지 않는다). */
export type DayTypeLoss = { emeans: number; lloyd: number; lloyd_starts: number; shown: { emeans: string; lloyd: string }; note: string };
/** 난수 시드 다섯의 배정 일치도(조정 랜드 지수) — 첫 시드가 모형, 나머지 넷과 견준다. */
export type DayTypeAgreement = { seeds: number[]; ari: number[]; shown: string[]; min: number; mean: number; same: boolean; note: string };
export type DayTypeExcluded = { total: number; by_reason: Record<string, number>; messages: Record<string, string | null>; rows: Skipped[] };
export type DayTypeSummary = {
  key: string; created_at: number | null; method: string; version: number; seed: number; minutes: number; k: number;
  grade: string; tickers: string[]; first_day: string; last_day: string; samples: number; synthetic: boolean;
};
export type DayTypeModel = DayTypeSummary & {
  grade_reason: string | null;
  request: { tickers: string[]; from: string; to: string; minutes: number; k: number };
  types: DayType[]; loss: DayTypeLoss; agreement: DayTypeAgreement;
  members: { date: string; ticker: string; type: number; start: string }[];
  days: string[]; starts: { start: string; samples: number }[]; excluded: DayTypeExcluded;
};
export type DayTypeLimits = {
  tickers: number; ticker_days: number; range_days: number; bytes: number; minutes: [number, number]; k: [number, number]; min_samples_per_type: number;
};
export type DayTypeAnswer = {
  model: DayTypeModel; created: boolean; stored: boolean; store_reason: string | null; notes: string[]; gate: { mock: boolean }; limits: DayTypeLimits;
};
export type DayTypeList = {
  available: boolean; reason: string | null; models: DayTypeSummary[]; hidden_synthetic: number | null; hidden_reason: string | null;
  gate: { mock: boolean }; limits: DayTypeLimits;
};
export type DayTypeRequest = { tickers: string[]; from: string; to: string; minutes: number; k: number };
/** 학습 거절의 세부 — 날이 모자라면 몇 날이 있었고 몇 날이 필요했는지 · 표본을 뺀 사유(서버 값 그대로). */
export type DayTypeRefusal = { code: string; reason: string; samples?: number; needed?: number; k?: number; excluded?: DayTypeExcluded };


// ── 시장 국면(일) — K1 (구현 계획 §7.1) ─────────────────────────────────────────────────
export type MarketIndex = "KOSPI" | "KOSDAQ";
/** 상한 — 서버의 상수 그대로(화면이 따로 두지 않는다). 국면 수 [하한, 상한] · 지수 목록. */
export interface MarketRegimeLimits {
  range_days: number; k: [number, number]; fit_days: number; window: number; seeds: number; history_calendar_days: number;
  indexes: { code: MarketIndex; name: string }[];
}
/** 그날 — 값이 없으면 `probs`·`top` 이 null 이고 `reason` 이 서버 문장이다(0 이 아니다). */
export interface MarketRegimeDay { date: string; probs: number[] | null; top: number | null; top_prob: number | null; reason: string | null }
export interface MarketRegimeState { state: number; days: number; share: number | null; mean_return: number | null; realized_vol: number | null }
export interface MarketRegimeAnswer {
  index: MarketIndex; name: string; k: number; from: string; to: string; mock: boolean;
  coverage: { ok: boolean | null; reason: string | null };
  notes: string[]; limits: MarketRegimeLimits;
  days: MarketRegimeDay[]; states: MarketRegimeState[]; transitions: number | null;
  /** 같은 자료의 BIC — 국면 수 "2" · "3" · "4" (고르지 않는다) */
  bic: Record<string, number | null> | null;
  agreement: { min: number; mean: number; seeds: number } | null;
  fit: { window_days: number; refits: number; seeds: number; failed: number } | null;
  grade: "E0" | "E3" | null; grade_reason: string | null; source: string | null;
  /** 계산하지 않은 까닭 — not_loaded · synthetic_in_production · bad_dates · store_error */
  empty: { reason: string; message: string } | null;
}
export type MarketRegimeRefusal = { code: string; reason: string; limit?: number; days?: number };

// ── 국면별 성과 나눔 — K2a (`GET /intraday/trials/{trial_key}/regime-split` · `src/engine/regime_split`) ───────────
/** 국면 하나의 몫 — 그 국면이 가장 컸던 날들의 합. 거래 수를 남기지 않은 옛 시행이면 거래 · 이긴 거래 · 승률이 `null`(0 이 아니다). */
export type RegimeSplitState = {
  state: number; days: number; low_conf_days: number;
  trades: number | null; wins: number | null; win_rate: number | null; pnl: number;
};
export type RegimeSplitBlock = {
  basis: "net" | "gross" | null;
  states: RegimeSplitState[];
  /** 국면을 알 수 없던 날 — 사유별 날 수(서버 글 그대로) */
  unknown: { days: number; trades: number | null; wins: number | null; win_rate: number | null; pnl: number; reasons: { reason: string; days: number }[] };
  /** 합계 — 0.5 미만 날 수는 국면들의 합(미상은 확률이 없어 세지 않는다) · 승률은 서버 값(화면이 셈하지 않는다) */
  total: { days: number; low_conf_days: number; trades: number | null; wins: number | null; win_rate: number | null; pnl: number };
  transitions: number;
  trades_known: boolean;
  trades_reason: string | null;
};
export interface RegimeSplitAnswer {
  trial_key: string; index: MarketIndex; name: string; k: number; from: string; to: string; mock: boolean;
  trial_grade: "E0" | "E3" | null; regime_grade: "E0" | "E3" | null; regime_grade_reason: string | null; source: string | null;
  coverage: { ok: boolean | null; reason: string | null } | null;
  split: RegimeSplitBlock | null;
  notes: string[];
  /** 나누지 않은 까닭 — no_flow · flow_mismatch · bad_flow · state_out_of_range · synthetic_trial_in_production · (국면) not_loaded · synthetic_in_production · bad_dates · store_error */
  empty: { reason: string; message: string } | null;
}

// ── 하루 유형 비율 × 국면 — K2b ──────────────────────────────────────────────────────────────
/** 한 칸 — 그 묶음(국면 · 미상 · 합계)에서 그 유형으로 배정된 표본 수 · 그 가운데 모형의 학습 날 표본 수 · 비율(분류된 표본이 0 이면 `null` — 0% 가 아니다). */
export type RegimeDayTypesCell = { type: number; n: number; in_sample: number; share: number | null };
/** 한 묶음 — 표본 · 유형을 정한 표본 · 표본 안 분류 · 유형별 칸 · 뺀 표본(사유 코드 → 수 · 서버 순서). */
export type RegimeDayTypesGroup = {
  samples: number; classified: number; in_sample: number; types: RegimeDayTypesCell[]; excluded: Record<string, number>;
};
export type RegimeDayTypesBlock = {
  k: number; types_k: number;
  states: (RegimeDayTypesGroup & { state: number })[];
  /** 국면을 알 수 없던 날의 표본 — 사유별 날 수 · 표본 수(서버 글 그대로) */
  unknown: RegimeDayTypesGroup & { reasons: { reason: string; days: number; samples: number }[] };
  /** 합계 — 국면들 + 미상(서버가 맞춘다 · 화면은 셈하지 않는다) */
  total: RegimeDayTypesGroup;
};
/** 쓴 모형의 사실 — 사실 줄(`facts`)은 서버 문장 그대로. 모형 기록을 읽지 못했으면 `overlap_days` 는 `null`. */
export type RegimeDayTypesModel = {
  key: string; minutes: number; k: number; first_day: string; last_day: string; tickers: string[]; same_tickers: boolean;
  overlap_days: number | null; grade: "E0" | "E3" | null; synthetic: boolean; facts: string[];
};
export interface RegimeDayTypesAnswer {
  trial_key: string; index: MarketIndex; name: string; k: number; from: string; to: string; mock: boolean;
  trial_grade: "E0" | "E3" | null; model: RegimeDayTypesModel;
  regime_grade: "E0" | "E3" | null; regime_grade_reason: string | null; source: string | null;
  coverage: { ok: boolean | null; reason: string | null } | null;
  /** 지금 다시 읽은 표본(봉)의 등급 — 시행 등급과 따로다. 표본이 없으면 `null` + 사유 */
  samples_grade: "E0" | "E3" | null; samples_grade_reason: string | null; sources: Record<string, number> | null;
  /** 뺀 사유 코드 → 서버 문장(하루 유형 학습 문과 같은 문장 · 모르는 사유는 `null`) */
  excluded_messages: Record<string, string | null>;
  table: RegimeDayTypesBlock | null;
  notes: string[];
  /** 세지 않은 까닭 — not_loaded · model_unreadable · state_out_of_range · bad_samples · synthetic_trial_in_production · synthetic_samples_in_production · (국면) 사유 그대로 */
  empty: { reason: string; message: string } | null;
}

// ── 하루 유형 비중을 더한 시장 국면 — K5 (`POST /intraday/market-regime/day-type-counts` · `GET …/day-type-input`) ───────────
/** 비중 세기의 요청 — 위의 국면 칸(지수 · 기간)과 이 절의 모형 · 바구니. 유형은 세기에 들지 않는다(센 값은 모든 유형의 이름표다). */
export interface DayTypeCountsRequest { model: string; tickers: string[]; index: MarketIndex; from: string; to: string }
/** 한 번의 세기 부름이 남긴 진행 — 센 날 = 바구니 전부를 지금 서명으로 센 날 · 낡은 날 = 일파일 · 장 시각 · 게이트가 바뀌어 다시 셀 날. */
export interface DayTypeCountsAnswer {
  model: string; index: MarketIndex; from: string; to: string; tickers: string[];
  needed_days: number; counted_days: number; remaining_days: number; stale_days: number; done: boolean;
  first_day: string | null; last_day: string | null; next_day: string | null;
  this_request: { days: number; rows: number; stale_rows: number; bytes: number; seconds: number; stopped: "budget" | "bytes" | null };
  excluded_by_reason: Record<string, number>; excluded_messages: Record<string, string | null>;
  grade: "E0" | "E3" | null; grade_reason: string; gate: { mock: boolean };
  limits: { budget_sec: number; bytes: number; tickers: number; window: number; history_calendar_days: number };
}
/** 판정 기간의 날마다 그날 국면이 쓴 비중(전 거래일까지 20거래일) — 모르면 `value` 가 null 이고 `reason` · `message` 가 서버 코드와 문장이다(0 이 아니다). */
export interface ShareDay { date: string; value: number | null; samples: number; reason: string | null; message: string | null }
/** 비중을 더한 답의 국면별 중심(마지막 적합) — 20거래일 로그 수익 · 실현 변동성(연율) · 하루 유형 비중. */
export interface RegimeCenter { state: number; r20: number; sigma20: number; share: number }
export type MarketRegimeShareAnswer = MarketRegimeAnswer & {
  centers?: RegimeCenter[] | null;
  fit: (NonNullable<MarketRegimeAnswer["fit"]> & { renumbered?: number; renumbered_months?: string[] }) | null;
};
export interface DayTypeInputAnswer {
  index: MarketIndex; name: string; k: number; from: string; to: string; mock: boolean;
  model: { key: string; minutes: number; k: number; first_day: string; last_day: string; tickers: string[]; grade: "E0" | "E3" | null; synthetic: boolean };
  types: number[]; tickers: string[]; window: number;
  /** 지수만의 국면 — 시장 국면 문의 답 그대로 */
  index_only: MarketRegimeAnswer;
  /** 지수 + 하루 유형 비중(셋째 특징)의 국면 — 한계 문장은 셋째 특징을 넣은 문장이다 */
  with_share: MarketRegimeShareAnswer;
  /** 지수가 비어 비중을 쓸 데가 없었으면 null(두 답의 `empty` 가 사유를 말한다) */
  share: {
    days: ShareDay[]; unknown_by_reason: { reason: string; days: number; message: string }[];
    classified: number; in_sample: { samples: number; days: number }; partial_days: number;
    excluded_by_reason: Record<string, number>; excluded_messages: Record<string, string | null>;
    grade: "E0" | "E3" | null; grade_reason: string;
  } | null;
  counts: { needed_days: number; counted_days: number; remaining_days: number; stale_days: number; first_day: string | null; last_day: string | null } | null;
  compare: { both_days: number; differ_days: number } | null;
  facts: string[]; notes: string[];
}
export type ShareRefusal = { code: string; reason: string };
