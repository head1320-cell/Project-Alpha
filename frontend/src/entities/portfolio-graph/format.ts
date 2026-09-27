/**
 * 파일 포맷 ↔ 캔버스 — ★순수 함수만★ (BI3)
 * ==========================================================================
 * 스펙 §4.1. 두 약속:
 *   1. **왕복** — `toDoc(fromDoc(doc))` 는 같은 노드 id·타입·파라미터·위치·링크를 돌려준다.
 *   2. **아무것도 버리지 않는다** — 카탈로그에 없는 노드 타입도, 없는 포트를 가리키는
 *      링크도 캔버스에 뜬다. 모르는 노드는 원본 type·params 를 그대로 들고 빨갛게 그려지고,
 *      없는 포트는 그 노드에 "미상 포트" 로 붙는다. 조용히 빠지면 다음에 내보낼 때
 *      사용자가 모르는 사이 그래프가 줄어든다.
 */
import type { Edge, Node } from "reactflow";
import {
  GRAPH_FORMAT,
  GRAPH_VERSION,
  type CatalogPort,
  type GraphDoc,
  type GraphDocEdge,
  type GraphDocNode,
  type GraphGroup,
  type NodeCatalogEntry,
} from "./types";

/** reactflow 노드 타입 — 모든 그래프 노드는 카탈로그로 그리는 범용 노드 하나다. */
export const PG_NODE_TYPE = "pg";

export interface PgNodeData {
  /** 그래프 노드 타입(`optimizer` 등) — reactflow 의 `type` 과 다른 칸이다. */
  kind: string;
  params: Record<string, unknown>;
  /** 카탈로그에 없는 타입이면 사유. 원본은 `kind`·`params` 에 그대로 있다. */
  unknownReason?: string | null;
  /** 카탈로그에 없는 포트를 가리키는 링크가 있을 때 — 버리지 않고 여기 붙인다. */
  extraInputs?: string[];
  extraOutputs?: string[];
}

export type PgNode = Node<PgNodeData>;

export interface ParseResult {
  doc: GraphDoc | null;
  problems: string[];
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * 파일 텍스트 → 문서. ★다른 포맷·버전은 불러오지 않는다★ — 이 파일이 무엇을 뜻하는지 모르면
 * 캔버스에 그리는 것 자체가 추측이다. 노드 타입이 모르는 것인지는 여기서 보지 않는다
 * (그것은 `fromDoc` 이 미상 노드로 그린다).
 */
export function parseFile(text: string): ParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return { doc: null, problems: [`JSON 이 아닙니다 — ${(e as Error).message}`] };
  }
  if (!isObj(raw)) return { doc: null, problems: ["문서가 객체가 아닙니다."] };
  const problems: string[] = [];
  if (raw.format !== GRAPH_FORMAT) {
    problems.push(`포트폴리오 그래프 파일이 아닙니다 — format=${JSON.stringify(raw.format)}, `
      + `기대값 "${GRAPH_FORMAT}".`);
  }
  if (raw.version !== GRAPH_VERSION) {
    problems.push(`지원하지 않는 버전입니다 — version=${JSON.stringify(raw.version)}, `
      + `이 화면은 ${GRAPH_VERSION} 만 읽습니다.`);
  }
  if (!Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) {
    problems.push("nodes·edges 가 목록이 아닙니다.");
  }
  if (problems.length) return { doc: null, problems };

  const nodes: GraphDocNode[] = [];
  const seen = new Set<string>();
  for (const [i, n] of (raw.nodes as unknown[]).entries()) {
    if (!isObj(n) || typeof n.id !== "string" || !n.id || typeof n.type !== "string") {
      problems.push(`노드 #${i + 1} 에 id·type 이 없습니다.`);
      continue;
    }
    if (seen.has(n.id)) {
      problems.push(`노드 id 중복: ${n.id}`);
      continue;
    }
    seen.add(n.id);
    const pos = isObj(n.position) ? n.position : {};
    nodes.push({
      id: n.id,
      type: n.type,
      params: isObj(n.params) ? n.params : {},
      position: {
        x: typeof pos.x === "number" ? pos.x : 0,
        y: typeof pos.y === "number" ? pos.y : i * 140,
      },
    });
  }
  const edges: GraphDocEdge[] = [];
  for (const [i, e] of (raw.edges as unknown[]).entries()) {
    if (!isObj(e) || [e.source, e.source_port, e.target, e.target_port]
      .some((v) => typeof v !== "string" || !v)) {
      problems.push(`링크 #${i + 1} 에 source·source_port·target·target_port 가 없습니다.`);
      continue;
    }
    if (!seen.has(e.source as string) || !seen.has(e.target as string)) {
      problems.push(`링크 #${i + 1} 이 없는 노드를 가리킵니다 (${e.source} → ${e.target}).`);
      continue;
    }
    edges.push({
      id: typeof e.id === "string" && e.id ? e.id
        : `${e.source}.${e.source_port}->${e.target}.${e.target_port}`,
      source: e.source as string, source_port: e.source_port as string,
      target: e.target as string, target_port: e.target_port as string,
    });
  }
  // 묶음 상자(BL1) — 없는 노드를 가리키는 구성원은 빼고, 비면 묶음도 뺀다(말하고).
  const groups: GraphGroup[] = [];
  if (Array.isArray(raw.groups)) {
    for (const [i, g] of (raw.groups as unknown[]).entries()) {
      if (!isObj(g) || typeof g.id !== "string" || !Array.isArray(g.members)) {
        problems.push(`묶음 #${i + 1} 에 id·members 가 없어 건너뛰었어요.`);
        continue;
      }
      const members = (g.members as unknown[]).filter((m): m is string => typeof m === "string" && seen.has(m));
      if (!members.length) { problems.push(`묶음 "${String(g.label ?? g.id)}" 에 남은 노드가 없어 건너뛰었어요.`); continue; }
      const strategy = g.kind === "strategy";
      groups.push({ id: g.id, label: typeof g.label === "string" ? g.label : g.id, members, collapsed: g.collapsed === true,
                    // 전략 상자(BM C2) — 선택 칸. 모르는 값은 버리고 그냥 묶음으로 읽는다(옛 문서는 그대로).
                    ...(strategy ? {
                      kind: "strategy" as const,
                      color: Number.isInteger(g.color) && (g.color as number) >= 0 ? (g.color as number) % 6 : 0,
                      output: typeof g.output === "string" && members.includes(g.output) ? g.output : null,
                    } : {}) });
    }
  }
  const meta = isObj(raw.meta) ? {
    name: typeof raw.meta.name === "string" ? raw.meta.name : undefined,
    exported_at: typeof raw.meta.exported_at === "string" ? raw.meta.exported_at : undefined,
  } : undefined;
  return {
    doc: { format: GRAPH_FORMAT, version: GRAPH_VERSION, meta, nodes, edges, ...(groups.length ? { groups } : {}) },
    problems,
  };
}

const portNames = (ps: CatalogPort[] | undefined) => new Set((ps ?? []).map((p) => p.name));

/** 문서 → reactflow. 모르는 타입·포트는 표시해서 남긴다. */
export function fromDoc(doc: GraphDoc, catalog: NodeCatalogEntry[]): { nodes: PgNode[]; edges: Edge[] } {
  const byType = new Map(catalog.map((c) => [c.type, c]));
  const extraIn = new Map<string, Set<string>>();
  const extraOut = new Map<string, Set<string>>();
  const kindOf = new Map(doc.nodes.map((n) => [n.id, n.type]));
  for (const e of doc.edges) {
    const src = byType.get(kindOf.get(e.source) ?? "");
    const dst = byType.get(kindOf.get(e.target) ?? "");
    if (!portNames(src?.outputs).has(e.source_port)) {
      extraOut.set(e.source, (extraOut.get(e.source) ?? new Set()).add(e.source_port));
    }
    if (!portNames(dst?.inputs).has(e.target_port)) {
      extraIn.set(e.target, (extraIn.get(e.target) ?? new Set()).add(e.target_port));
    }
  }
  const nodes: PgNode[] = doc.nodes.map((n) => ({
    id: n.id,
    type: PG_NODE_TYPE,
    position: { ...n.position },
    data: {
      kind: n.type,
      params: { ...n.params },
      unknownReason: byType.has(n.type) ? null
        : `모르는 노드 타입 "${n.type}" — 이 서버에 없는 노드입니다(다른 버전에서 만든 파일일 수 `
          + "있습니다). 원본 설정은 보존되고, 내보내면 그대로 다시 저장됩니다.",
      extraInputs: [...(extraIn.get(n.id) ?? [])],
      extraOutputs: [...(extraOut.get(n.id) ?? [])],
    },
  }));
  const edges: Edge[] = doc.edges.map((e) => ({
    id: e.id,
    source: e.source,
    sourceHandle: e.source_port,
    target: e.target,
    targetHandle: e.target_port,
  }));
  return { nodes, edges };
}

/** reactflow → 문서. 실행 결과는 넣지 않는다(파라미터·위치만). */
export function toDoc(nodes: PgNode[], edges: Edge[], meta?: GraphDoc["meta"], groups?: GraphGroup[]): GraphDoc {
  return {
    format: GRAPH_FORMAT,
    version: GRAPH_VERSION,
    ...(meta ? { meta } : {}),
    ...(groups?.length ? { groups: groups.map((g) => ({ ...g, members: [...g.members] })) } : {}),
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.kind,
      params: { ...n.data.params },
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      source_port: e.sourceHandle ?? "",
      target: e.target,
      target_port: e.targetHandle ?? "",
    })),
  };
}

/** 사람이 읽는 파일 이름 — `이름.portfolio-graph.json`. */
export function exportFileName(name: string | undefined, now = new Date()): string {
  const base = (name || `portfolio-${now.toISOString().slice(0, 10)}`)
    .replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "") || "portfolio";
  return `${base}.portfolio-graph.json`;
}
