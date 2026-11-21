/**
 * 단계 건너뛰기 (2026-11-13 · 설계 `docs/superpowers/specs/2026-11-13-canvas-bypass-compare-design.md` §1)
 * ==========================================================================
 * "이 단계 없이 계산하면?" — 건너뛴 노드는 ★받은 것을 그대로 다음으로 넘긴다★. 그러려면 입력과 출력의 종류가 같아야 한다.
 * 서버 노드 목록 88종 가운데 그런 것은 넷이다(2026-11-13 관측 — 종류가 늘면 여기에 더한다. 화면이 임의의 노드를 건너뛰게 하지 않는다).
 *
 * ★화면이 선을 돌려 잇는다 · 서버 0줄★ — 계산 요청을 만들 때 건너뛴 노드를 빼고, 그 노드의 통과 입력에 이어진 원천을 출력의 대상들에 잇는다.
 * 서버는 실제로 계산한 그래프만 보므로 계보·증거 관문은 사실 그대로다(건너뛴 노드는 계산되지 않았고 계보에도 없다).
 * 순수 함수 — 무엇을 건너뛸 수 있는지와 왜 안 되는지, 그리고 서버로 보낼 문서만 정한다. 표시(`bypass`)는 서버로 가지 않는다.
 *
 * ★이 기능이 보여 주는 것은 같은 과거에서의 전달 차이다 — 그 단계가 앞으로도 도움이 된다는 증거가 아니다.★
 */
import type { GraphDoc, GraphDocEdge, NodeCatalogEntry } from "./types";

/** 건너뛸 수 있는 종류 → 통과 포트(받는 포트 · 내는 포트)와 넘기는 것의 이름. */
export const BYPASS_PORTS: Record<string, { input: string; output: string; what: string }> = {
  screener: { input: "universe", output: "universe", what: "유니버스" },
  neutralize: { input: "weights", output: "weights", what: "비중" },
  exposure_overlay: { input: "weights", output: "weights", what: "비중" },
  company_views: { input: "views", output: "views", what: "투자 뷰" },
};

export type BypassCheck = { ok: true; input: string; output: string } | { ok: false; reason: string };

export const bypassable = (kind: string): boolean => kind in BYPASS_PORTS;

/** 종류와 "그 입력 포트에 선이 있는가"만으로 정한다 — 문서 모양·캔버스 모양이 같은 규칙을 쓴다. */
function check(kind: string, hasInput: (port: string) => boolean, catalog: NodeCatalogEntry[]): BypassCheck {
  const spec = BYPASS_PORTS[kind];
  const entry = catalog.find((c) => c.type === kind);
  if (!spec || !entry) return { ok: false, reason: "이 노드는 건너뛸 수 없습니다 — 받은 것을 그대로 넘길 수 있는 종류가 아닙니다." };
  const inP = entry.inputs.find((p) => p.name === spec.input);
  const outP = entry.outputs.find((p) => p.name === spec.output);
  // 서버의 포트가 달라졌으면 조용히 통과시키지 않는다 — 종류가 다른 것을 이으면 계산이 거절된다.
  if (!inP || !outP || inP.type !== outP.type) return { ok: false, reason: "이 노드는 건너뛸 수 없습니다 — 서버의 입력·출력 종류가 달라졌습니다." };
  if (!hasInput(spec.input)) return { ok: false, reason: `앞에 ${spec.what} 입력이 이어져 있어야 건너뛸 수 있습니다 — 그대로 넘길 것이 없습니다.` };
  return { ok: true, input: spec.input, output: spec.output };
}

/** 문서 모양(`type` · `source_port`/`target_port`). */
export function canBypassDoc(node: { id: string; type: string }, edges: GraphDocEdge[], catalog: NodeCatalogEntry[]): BypassCheck {
  return check(node.type, (port) => edges.some((e) => e.target === node.id && e.target_port === port), catalog);
}

type RfEdge = { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null };
/** 캔버스 모양(`data.kind` · `sourceHandle`/`targetHandle`). */
export function canBypass(node: { id: string; data: { kind: string } }, edges: RfEdge[], catalog: NodeCatalogEntry[]): BypassCheck {
  return check(node.data.kind, (port) => edges.some((e) => e.target === node.id && e.targetHandle === port), catalog);
}

/** 캔버스에서 ★실제로★ 건너뛰는 노드 — 표시가 있고 조건도 맞는 것(표시만 있고 입력이 끊긴 노드는 그대로 계산되므로 들지 않는다). */
export function skippedIds(nodes: { id: string; data: { kind: string; bypass?: boolean } }[], edges: RfEdge[], catalog: NodeCatalogEntry[]): Set<string> {
  return new Set(nodes.filter((n) => n.data.bypass && canBypass(n, edges, catalog).ok).map((n) => n.id));
}

/**
 * 서버로 보낼 문서 — 건너뛴 노드를 빼고 선을 돌려 잇는다. 연달아 건너뛴 노드도 풀린다.
 * - 건너뛴 노드로 들어가는 선은 모두 뺀다(통과 입력은 원천으로 이어지고, 신호·국면 같은 다른 입력은 쓰이지 않는다).
 * - 표시가 있어도 조건이 안 맞으면(입력이 끊겼다) 건너뛰지 않는다 — 그 노드는 그대로 계산된다.
 * - ★건너뛴 것도 표시도 없으면 받은 문서를 그대로 돌려준다(같은 객체)★ — 요청 본문이 바이트 그대로다.
 * - 돌려주는 문서에는 `bypass` 칸이 없다(서버가 모르는 칸을 보내지 않는다).
 */
export function applyBypassDoc(doc: GraphDoc, catalog: NodeCatalogEntry[]): { doc: GraphDoc; skipped: string[] } {
  if (!doc.nodes.some((n) => n.bypass)) return { doc, skipped: [] };
  const skip = new Map<string, { input: string; output: string }>();
  for (const n of doc.nodes) {
    if (!n.bypass) continue;
    const c = canBypassDoc(n, doc.edges, catalog);
    if (c.ok) skip.set(n.id, c);
  }
  const origin = (id: string, port: string, seen: Set<string>): { source: string; source_port: string } | null => {
    const s = skip.get(id);
    if (!s || port !== s.output) return { source: id, source_port: port };
    if (seen.has(id)) return null;
    seen.add(id);
    const inc = doc.edges.find((e) => e.target === id && e.target_port === s.input);
    return inc ? origin(inc.source, inc.source_port, seen) : null;
  };
  const edges: GraphDocEdge[] = [];
  for (const e of doc.edges) {
    if (skip.has(e.target)) continue;
    if (!skip.has(e.source)) { edges.push(e); continue; }
    const o = origin(e.source, e.source_port, new Set());
    if (o) edges.push({ ...e, source: o.source, source_port: o.source_port });
  }
  const nodes = doc.nodes.filter((n) => !skip.has(n.id)).map((n) => {
    if (!n.bypass) return n;
    const { bypass: _drop, ...rest } = n;
    return rest;
  });
  return { doc: { ...doc, nodes, edges }, skipped: [...skip.keys()] };
}
