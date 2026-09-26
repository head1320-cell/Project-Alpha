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

export interface GraphDoc {
  format: typeof GRAPH_FORMAT;
  version: typeof GRAPH_VERSION;
  meta?: { name?: string; exported_at?: string };
  nodes: GraphDocNode[];
  edges: GraphDocEdge[];
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
  widget?: "slider" | "cards" | "filter";
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
  gates?: GateReport;
}
