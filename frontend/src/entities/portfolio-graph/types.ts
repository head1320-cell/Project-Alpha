/**
 * 포트폴리오 그래프 — 타입 (BI3)
 * ==========================================================================
 * 파일 포맷 `project-alpha.portfolio-graph` v1 (스펙 §4.1 · ADR 002).
 * ★이 포맷이 저장 계약이다★ — 지금은 내보내기/불러오기, 서버 저장이 생겨도 같은 문서.
 * 실행 결과는 담지 않는다(파라미터·위치만). 결과는 다시 실행해서 얻는다.
 */

export const GRAPH_FORMAT = "project-alpha.portfolio-graph";
export const GRAPH_VERSION = 1;

export interface GraphDocNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
  position: { x: number; y: number };
}

export interface GraphDocEdge {
  id: string;
  source: string;
  source_port: string;
  target: string;
  target_port: string;
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
  meta?: { name?: string; exported_at?: string };
  nodes: GraphDocNode[];
  edges: GraphDocEdge[];
  groups?: GraphGroup[];
  branches?: GraphBranch[];
  /** 그림 고정(BN N2) — 멀리서도 작은 그림을 보이는 노드 id. 화면 정보(서버는 읽지 않는다). */
  pinned?: string[];
}

// ── 카탈로그 (`GET /api/v1/allocation/graph/node-types`) ────────────────────

export interface CatalogPort {
  name: string;
  type: string;
  required?: boolean;
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
  widget?: "slider" | "cards" | "filter" | "text" | "pick" | "tickers";
  /** `widget: "pick"` 가 부를 목록 이름(BK W5) — `strategies` · `research_runs`. 주소가 아니다. */
  source?: string;
  ends?: [string, string];
  presets?: { label: string; value: unknown }[];
  options?: Record<string, string>;
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
}

export interface WorkflowStage { key: string; label: string }

export interface NodeCatalog {
  format: string;
  version: number;
  port_types: string[];
  stages: WorkflowStage[];
  nodes: NodeCatalogEntry[];
}

// ── 검증·실행 보고 ──────────────────────────────────────────────────────────

export interface GraphError {
  code: string;
  message: string;
  node_id: string | null;
  edge_id: string | null;
}

export interface ValidateReport {
  ok: boolean;
  errors: GraphError[];
}

export type NodeStatus = "ok" | "blocked" | "failed";

export type TrustState = "confirmed" | "assumed" | "unknown" | "failed";

/** 서버가 만든 쉬운 말 설명(BJ1) — 화면은 그리기만 한다. */
export interface NodeExplain {
  title: string;
  headline?: { label: string; value: number | null; unit: string; text: string } | null;
  facts?: string[];
  trust?: { state: TrustState; text: string }[];
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
}
