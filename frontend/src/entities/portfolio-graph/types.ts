/**
 * 포트폴리오 그래프 — 타입 (BI3)
 * ==========================================================================
 * 파일 포맷 `project-alpha.portfolio-graph` v1 (스펙 §4.1 · ADR 002).
 * ★이 포맷이 저장 계약이다★ — 지금은 내보내기/불러오기, 서버 저장이 생겨도 같은 문서.
 * 실행 결과는 담지 않는다(파라미터·위치만). 결과는 다시 실행해서 얻는다.
 */

import type { GoalKey } from "./goals";

export const GRAPH_FORMAT = "project-alpha.portfolio-graph";
export const GRAPH_VERSION = 1;

export interface GraphDocNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
  position: { x: number; y: number };
  /** 말로 설계(AI4) — 칸 → 그 값을 말한 말씀 조각. 그 칸을 고치면 지운다. 서버 검증·계산은 보지 않는다. */
  said?: Record<string, string>;
}

export interface GraphDocEdge {
  id: string;
  source: string;
  source_port: string;
  target: string;
  target_port: string;
  /** 경유점(CF4c) — 선이 지나는 자리(캔버스 좌표). ★계산에는 끼지 않는 화면 정보★ — 서버는 읽지 않는다. */
  waypoints?: { x: number; y: number }[];
}

/** 묶음 상자(BL1) — ★계산에는 끼지 않는 화면 정보★. 서버는 이 칸을 읽지 않고, 파일에만 남는다. */
export interface GraphGroup {
  id: string;
  label: string;
  members: string[];
  collapsed?: boolean;
  /** 전략 상자(BM C2) — 비중을 내는 한 흐름. 없으면 그냥 묶음. 계산에는 끼지 않는다(화면 정보). */
  kind?: "group" | "strategy";
  /** 전략 띠 색(0~5). */
  color?: number;
  /** 전략의 비중을 내는 노드 id — 포트폴리오 노드에 잇는 출력. */
  output?: string | null;
}

/** 갈래(BM C3) — 뿌리 노드와 그 하류를 복제한 "이 조건이면?" 한 벌. 계산에는 끼지 않는 화면 정보(복제 노드는 보통 노드다). */
export interface GraphBranch {
  id: string;
  /** "갈래 B" … "갈래 E". */
  label: string;
  /** 복제한 뿌리(이 갈래 안의 id). */
  root: string;
  /** 원본 뿌리. */
  of_root: string;
  /** 복제 id → 원본 id. */
  map: Record<string, string>;
}

export interface GraphDoc {
  format: typeof GRAPH_FORMAT;
  version: typeof GRAPH_VERSION;
  /** `goal` — '목표로 시작'에서 고른 목표(AI1, 네 키만). 계산에는 끼지 않고 AI 추천의 근거가 된다(서버가 키를 자기 문장으로 바꾼다). */
  meta?: { name?: string; exported_at?: string; goal?: GoalKey };
  nodes: GraphDocNode[];
  edges: GraphDocEdge[];
  groups?: GraphGroup[];
  branches?: GraphBranch[];
  /** 그림 고정(BN N2) — 멀리서도 작은 그림을 보이는 노드 id. 화면 정보(서버는 읽지 않는다). */
  pinned?: string[];
  /** 접은 노드(CF1) — 머리 줄만 보이고 소켓이 머리 양끝에 모인다. 화면 정보(서버는 읽지 않는다). */
  folded?: string[];
}

// ── 카탈로그 (`GET /api/v1/allocation/graph/node-types`) ────────────────────

export interface CatalogPort {
  name: string;
  type: string;
  required?: boolean;
  /** 받는 쪽이 이 입력을 무엇에 쓰는지(BT1) — 서버가 확인한 곳만 있다. 없으면 화면은 그 줄을 생략한다. */
  role?: string;
  /** 입력: 보내는 쪽이 꼭 실어야 하는 값(BT1). */
  needs?: string[];
  /** 출력: 싣는 값 — 늘(`key`만) · 입력이 있으면(`when`) · 입력에서 넘김(`from`). */
  gives?: { key: string; when?: string; from?: string }[];
}

/** JSON Schema 의 쓰는 부분만 — 서버(pydantic)가 만든다. */
export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  pattern?: string;
  maxLength?: number;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  /** 화면 메타(BJ1) — 쉬운 이름·질문·기본/전문가 층·프리셋·선택지 라벨. 검증 규칙이 아니다. */
  "x-ui"?: ParamUi;
}

export interface ParamUi {
  label: string;
  tier: "basic" | "advanced";
  question?: string;
  help?: string;
  unit?: string;
  widget?: "slider" | "cards" | "filter" | "text" | "pick" | "tickers" | "per_port" | "per_port_number" | "constraints";
  /** `widget: "pick"` 가 부를 목록 이름(BK W5) — `strategies` · `research_runs`. 주소가 아니다. */
  source?: string;
  ends?: [string, string];
  presets?: { label: string; value: unknown }[];
  options?: Record<string, string>;
  /** 다른 칸이 이 값들 중 하나일 때만 보인다(BO O1) — 예: `{model: ["mv_utility"]}`. 규칙은 서버가 준다. */
  show_if?: Record<string, unknown[]>;
  /** 선택지 순서(BO O2) — 스키마 경로가 키 순서를 바꿀 수 있어 서버가 따로 준다. 없으면 받은 순서. */
  order?: string[];
  /** 비워 두면 서버가 쓰는 값(BO O1) — 표시만 한다. 문서에 이 값을 쓰지 않는다. */
  empty_value?: unknown;
  /** 선택지마다 한 줄 설명(BS4) — 무엇을 하는지. 낫다는 말이 아니다. */
  descriptions?: Record<string, string>;
  /** 전략마다 숫자(`per_port_number`)의 합이 이 값이어야 한다(BS4) — 화면은 합을 보여 줄 뿐, 판정은 서버가 한다. */
  sum_to?: number;
}

export interface NodeCatalogEntry {
  type: string;
  label: string;
  category: string;
  description: string;
  /** 퀀트 워크플로우 단계 키(`stages` 의 key). */
  stage: string;
  plain_label: string;
  plain_description: string;
  inputs: CatalogPort[];
  outputs: CatalogPort[];
  params_schema: JsonSchema | null;
  /** 저장하기 버튼이 있는 노드(BK0) — 저장은 `/graph/save` 로만, 계산은 쓰지 않는다. */
  savable?: boolean;
  /** 저장 버튼에 쓰는 말(BL2) — 누르면 일어나는 일. 저장하지 않는 노드는 null. */
  save_label?: string | null;
  /** 과거를 시뮬레이션하거나 그 기록을 읽는 노드(BT1). */
  simulates_history?: boolean;
}

export interface WorkflowStage { key: string; label: string }

export interface NodeCatalog {
  format: string;
  version: number;
  port_types: string[];
  stages: WorkflowStage[];
  nodes: NodeCatalogEntry[];
  /** 포트 타입 → 쉬운 이름(BT1 — 서버가 준다). */
  port_plain?: Record<string, string>;
  /** 관문 이름(BT1) — 계산 전 레일의 빈 역. */
  gates?: { key: string; label: string }[];
}

// ── 검증·실행 보고 ──────────────────────────────────────────────────────────

export interface GraphError {
  code: string;
  message: string;
  node_id: string | null;
  edge_id: string | null;
  /** 고치는 법 한 줄(BT1) — 서버가 쓴다. */
  fix?: string | null;
}

// ── 설계 절차 (BT1 — `/validate`·`/run` 의 `procedure`) ─────────────────────

export type StepNeed = "required" | "recommended" | "optional";
/** `partial` — 노드는 있는데 이 단계가 재는 관문을 아직 잴 수 없다(예: 종목만 있고 수익률이 없다). */
export type StepState = "filled" | "partial" | "empty" | "blocked";

export interface ProcedureStep {
  key: string;
  label: string;
  need: StepNeed;
  state: StepState;
  node_ids: string[];
  feeds_gates: string[];
  text: string;
}

/** 이을 선 — `@new` 는 붙일 새 노드. */
export interface AttachEdge { source: string; source_port: string; target: string; target_port: string }

export interface ProcedureSuggestion {
  action: "add" | "connect";
  kind: string | null;
  label: string | null;
  text: string;
  attach: AttachEdge[];
  unlocks: string[];
}

/** AI 추천(AI1) — 서버가 검사를 통과시킨 것만 온다(카탈로그·연결·근거 숫자·금지 표현). 설정값은 없다. */
export interface AiSuggestion { action: "add"; kind: string; label: string; attach: AttachEdge[]; reason: string }
/** 검사에서 빠진 AI 추천 — 무엇이 왜(서버 문장). */
export interface AiRejected { kind: string | null; code: string; reason: string }
/** `POST /api/v1/assist/canvas/suggest` — 쓸 수 있으면 통과·탈락, 못 쓰면 사유(★AI 글은 없다★). */
export type AssistSuggest =
  | { available: true; source: "claude"; model: string; suggestions: AiSuggestion[]; rejected: AiRejected[]; cached: boolean;
      usage: { input_tokens: number; output_tokens: number; cost_usd: number | null; cost_note: string | null } }
  | { available: false; source: "unavailable"; reason_code: string; reason: string };

/** AI 풀어 쓰기(AI2)에 보내는 사실 하나 — `/run` 의 설명과 봉인 그대로. */
export interface NarrateFact { node_id: string; explain: NodeExplain; sig: string }
/** 확인하지 못해 뺀 사실 — 어느 노드가 왜. */
export interface NarrateDropped { node_id: string | null; reason: string }
/** `POST /api/v1/assist/canvas/narrate` — 문단마다 근거 노드 · 연습용 경고는 서버가 붙인 것(`notice`). */
export type AssistNarrate =
  | { available: true; source: "claude"; model: string; paragraphs: { text: string; node_ids: string[] }[];
      rejected: { code: string; reason: string }[]; dropped: NarrateDropped[]; notice: string | null; cached: boolean;
      usage: { input_tokens: number; output_tokens: number; cost_usd: number | null; cost_note: string | null } }
  | { available: false; source: "unavailable"; reason_code: string; reason: string; dropped?: NarrateDropped[] };

/** 묻는 대상(AI3) — 고른 노드나 선. */
export interface AskTarget { kind: "node" | "edge"; id: string }
/** 돌려보내는 전달 점검 기록 — `/run` 의 기록에서 `sig` 칸을 뗀 것과 그 봉인. */
export interface AskRecord { edge_id: string; record: Omit<EdgeRecord, "sig">; sig: string }
/** 답이 댄 사실 줄 — 서버가 붙인 id 의 원문과 자리(화면은 `index` 로 "사실 2" 를 그린다). */
export interface AskFactRef { target_kind: "node" | "edge"; target_id: string; part: string; index: number; text: string }
export interface AskSentence { text: string; fact_ids: string[] }
export interface AskAnswer { answerable: boolean; cannot: string | null; sentences: AskSentence[] }
/** 확인하지 못해 뺀 것 — 노드 설명이면 `node_id`, 전달 점검이면 `edge_id`. */
export interface AskDropped { node_id?: string | null; edge_id?: string | null; reason: string }
/** `POST /api/v1/assist/canvas/ask` — 범위(조상 전부 + 그것 + 바로 아래) 안 봉인한 설명·기록만 근거 · 문장마다 사실 줄. */
export type AssistAsk =
  | { available: true; source: "claude"; model: string; answer: AskAnswer; facts: Record<string, AskFactRef>;
      rejected: { code: string; reason: string }[]; dropped: AskDropped[]; notice: string | null;
      scope: { nodes: string[]; edges: string[] }; cached: boolean;
      usage: { input_tokens: number; output_tokens: number; cost_usd: number | null; cost_note: string | null } }
  | { available: false; source: "unavailable"; reason_code: string; reason: string; dropped?: AskDropped[] };

/** `POST /api/v1/assist/canvas/guide` — 써 볼 도구 1~2(적용되는 것만 · 이유의 숫자는 상태 안에서만). 못 보이면 사유(화면은 규칙 길잡이 줄을 둔다). */
/** 말로 설계(AI4) 초안 — 서버가 검사를 마친 것만. 값(`value`)은 서버가 말씀 조각(`quote`)에서 읽었다. */
export interface DraftAdd { ref: string; id: string; kind: string; label: string }
export interface DraftConnect { id: string; source: string; source_port: string; target: string; target_port: string }
export interface DraftSet { node: string; field: string; label: string; value: unknown; display: string; quote: string;
  read: "preset" | "option" | "number" | "tickers" }
export interface DraftEmpty { node: string; field?: string; port?: string | null; why: string }
export interface DraftBody { summary: string | null; add: DraftAdd[]; connect: DraftConnect[]; set: DraftSet[]; empty: DraftEmpty[] }
export type AssistDraft =
  | { available: true; source: "claude"; model: string; understood: boolean; cannot: string | null; draft: DraftBody;
      rejected: { op: string; code: string; reason: string }[]; cached: boolean;
      usage: { input_tokens: number; output_tokens: number; cost_usd: number | null; cost_note: string | null } }
  | { available: false; source: "unavailable"; reason_code: string; reason: string };

export type AssistGuide =
  | { available: true; source: "claude"; model: string; tips: { feature: string; label: string; why: string }[];
      rejected: { code: string; reason: string }[]; cached: boolean;
      usage: { input_tokens: number; output_tokens: number; cost_usd: number | null; cost_note: string | null } }
  | { available: false; source: "unavailable"; reason_code: string; reason: string };

export interface Procedure {
  steps: ProcedureStep[];
  next: ProcedureSuggestion | null;
  by_gate: Record<string, ProcedureSuggestion | null>;
  /** 노드마다 첫 빠진 입력의 고치는 법(BT7) — 카드의 "고치는 법" 줄. 고칠 길이 없는 노드는 없다. */
  fixes?: Record<string, ProcedureSuggestion>;
  done_text: string | null;
}

/** 관계 문장(CF3) — 선 하나가 무엇을 어디서 어디로, 무엇에 쓰이려고 나르는지(서버가 쓴다). */
export interface EdgeRelation {
  text: string;
  /** 흐르는 값의 쉬운 이름(포트 타입). */
  flows: string;
  /** 받는 포트의 역할 — 서버가 확인하지 못했으면 `null`(문장에 둘째 문장이 없다). */
  role: string | null;
  required: boolean;
  /** 선 요약 — 계산 전이면 `null`. */
  brief: string | null;
}

/** 전달 점검의 문제 단계(CF3) — 빠짐 · 바뀜 · 구조(수학적 사실) · 쓰지 않음. */
export type IssueLevel = "lost" | "changed" | "structural" | "unused";

/** 건너간 것 하나 — 값에서 잰 것만(좋다·나쁘다 말 없음). */
export interface EdgeFact {
  key: string;
  label: string;
  text: string;
  value?: number | string | boolean | null;
}

export interface EdgeIssue {
  level: IssueLevel;
  code: string;
  text: string;
  /** 고치는 법(글만) — 없을 수 있다. */
  fix?: string;
}

/** 선 하나의 전달 점검(CF3). ★`issues: null` 은 점검하지 않음(사유 있음)이고, `[]` 는 점검했고 찾지 못함이다★. */
export interface EdgeRecord {
  source: string;
  target: string;
  facts: EdgeFact[] | null;
  facts_reason: string | null;
  checks: string[];
  issues: EdgeIssue[] | null;
  issues_reason: string | null;
  /** 서버 봉인(AI3) — 이 기록이 그 서버가 지금 그래프에 대해 낸 것인지 묻기 때 확인한다. 기록(이 칸 빼고)에 대한 것. */
  sig?: string;
}

export interface ValidateReport {
  ok: boolean;
  errors: GraphError[];
  procedure?: Procedure | null;
  /** 관계 문장(CF3) — 계산 전이라 선 요약이 없다. */
  relations?: Record<string, EdgeRelation>;
}

export type NodeStatus = "ok" | "blocked" | "failed";

/** 계산 진행 곁줄 이벤트(CF5a · `GET /allocation/graph/progress/{rid}`) — 보기일 뿐, 최종 상태·시간은 보고서가 정한다. */
export type RunEvent =
  | { type: "plan"; order: string[] }
  | { type: "node_start"; id: string }
  | { type: "node_done"; id: string; status: NodeStatus; elapsed_ms: number | null }
  | { type: "end" }
  | { type: "timeout" };

export type TrustState = "confirmed" | "assumed" | "unknown" | "failed";

/** 서버가 만든 쉬운 말 설명(BJ1) — 화면은 그리기만 한다. */
export interface NodeExplain {
  title: string;
  headline?: { label: string; value: number | null; unit: string; text: string } | null;
  facts?: string[];
  /** `kind: "practice"` — 연습용(합성) 데이터라는 줄(BT7). 화면의 연습용 칩은 문구가 아니라 이 표시를 본다.
   *  `kind: "fallback"` — 고른 방식 대신 다른 비중이 쓰였다는 줄(CF3). */
  trust?: { state: TrustState; text: string; kind?: "practice" | "fallback" }[];
  unmeasured?: string[];
}

export interface NodeRunResult {
  type: string | null;
  status: NodeStatus;
  reason: string | null;
  /** 노드마다 모양이 다르다 — 결과 패널이 타입별로 읽는다. 막힌 노드는 `null`. */
  view: Record<string, unknown> | null;
  provenance: Record<string, unknown>;
  explain?: NodeExplain | null;
  /** 설명 봉인(AI2) — 서버가 이 설명을 이 그래프에 대해 냈다는 HMAC. AI 풀어 쓰기가 설명과 함께 그대로 돌려보낸다(화면은 만들지 않는다). */
  explain_sig?: string | null;
  /** 하류로 흐르는 계보(BK0) — 연습용 · 시점 정합 · 노출 조절. */
  lineage?: NodeLineage;
  /** 미리보기 해시 — 저장할 때 "본 것 == 지금 계산" 확인에 쓴다. 계산 못 한 노드는 `null`. */
  view_hash?: string | null;
  /** ★이번 "여기까지 계산" 에서 계산하지 않은 노드★(BL1) — 화면이 이전 결과를 남기며 붙인다. 서버는 내지 않는다. */
  previous?: boolean;
  /** 캔버스 위 작은 그림(BM C1) — ★서버가 보기에서 고른 수 그대로★. 그릴 수 없으면 `null`(빈 그림을 지어내지 않는다). */
  glance?: NodeGlance | null;
  /** 이 노드의 계산 시간(ms) — 돌지 않은 노드(막힘)는 `null`. */
  elapsed_ms?: number | null;
  /** 출력 포트마다 흐르는 값의 한 줄(서버) — 선 가운데에 그린다. 요약이 없는 포트는 키가 없다. */
  briefs?: Record<string, string>;
}

export type GlanceKind = "bars" | "line" | "hist" | "values";

/** 작은 그림 — 점 값이 `null` 이면 모르는 값이다(0 이 아니다). */
export interface NodeGlance {
  kind: GlanceKind;
  points: { label: string; value: number | null }[];
  unit: string | null;
  caption: string | null;
}

export interface NodeLineage {
  pit: "pit" | "unknown" | "forward_only" | null;
  practice: boolean;
  overlay: boolean;
  sources: string[];
}

export type SaveResult =
  | { ok: true; saved_id: string | null; text: string | null; node_id: string }
  | { ok: false; code: "no_node" | "not_savable" | "not_ok" | "stale" | "save_failed"; message: string };

export type GateState = "confirmed" | "assumed" | "partial" | "unknown" | "skipped" | "failed";

export interface Gate {
  key: string;
  label: string;
  state: GateState;
  reasons: { state: GateState | TrustState; text: string }[];
  /** 이 관문 판정에 쓰인 노드(BT1). */
  node_ids?: string[];
}

export interface GateReport {
  gates: Gate[];
  summary: { confirmed: number; total: number; text: string; note: string };
}

export interface RunReport extends ValidateReport {
  order: string[];
  nodes: Record<string, NodeRunResult>;
  gates?: GateReport | null;
  /** 부분 계산(BL1 "여기까지 계산") — 있으면 관문은 `null` 이고 `gates_reason` 이 이유를 말한다. */
  partial?: { targets: string[]; computed: string[] };
  gates_reason?: string;
  /** 선마다 전달 점검(CF3) — 받아들여진 선 · 보내는 노드가 계산된 선만. */
  edges?: Record<string, EdgeRecord>;
}

/** 갈래 비교의 다중 비교 보정(BO O3) — 서버 `/graph/branch-evidence` 응답. 못 잰 값은 null + 사유. */
export interface BranchEvidenceRow {
  label: string; t: number; sr: number | null; skew: number | null; kurt: number | null;
  psr0: number | null; dsr: number | null; reason: string | null;
  /** 닮음을 뺀 독립 수(N_eff)로 보정한 확률(BP P3) — N_eff 를 못 재거나 2 미만이면 null. */
  dsr_eff: number | null;
}
export interface BranchEvidence {
  n: number; sr0: number | null; var_sr: number | null; rows: BranchEvidenceRow[]; reason: string | null; note: string;
  /** 수익 흐름 상관의 참여비로 추정한 독립 시행 수(BP P3) · 그 수의 기대 최대 SR · 못 낸 사유. */
  n_eff: number | null; sr0_eff: number | null; n_eff_reason: string | null;
}
