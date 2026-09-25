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
}

export interface NodeCatalogEntry {
  type: string;
  label: string;
  category: string;
  description: string;
  inputs: CatalogPort[];
  outputs: CatalogPort[];
  params_schema: JsonSchema | null;
}

export interface NodeCatalog {
  format: string;
  version: number;
  port_types: string[];
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

export interface NodeRunResult {
  type: string | null;
  status: NodeStatus;
  reason: string | null;
  /** 노드마다 모양이 다르다 — 결과 패널이 타입별로 읽는다. 막힌 노드는 `null`. */
  view: Record<string, unknown> | null;
  provenance: Record<string, unknown>;
}

export interface RunReport extends ValidateReport {
  order: string[];
  nodes: Record<string, NodeRunResult>;
}
