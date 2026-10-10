/**
 * 부품 (BT6) — 바꿔 끼우기 · 혼자 쓰는 도구 · 지금 이을 수 있는 종류
 * ==========================================================================
 * - **바꿔 끼우기**: 같은 단계의 다른 종류로 바꾸되 자리와 선을 그대로 둔다. 들어오는 선은 새 종류의 같은 타입 입력에(같은 이름을
 *   먼저, 입력 하나에 선 하나), 나가는 선은 같은 타입 출력에 다시 맞춘다. 하나라도 맞출 수 없으면 그 종류는 후보가 아니다 —
 *   선을 조용히 버리지 않는다.
 * - **혼자 쓰는 도구**: 입력도 출력도 없는 종류(포트를 새로 만들지 않는다 — 백엔드 계약 변경이라 하지 않는다).
 * - **지금 이을 수 있어요**: 고른 노드의 출력 타입을 받는 종류, 단계 순서대로.
 */
import type { NodeCatalogEntry } from "./types";

export interface SwapNode { id: string; data: { kind: string } }
export interface SwapEdge { id: string; source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }

/** 입력도 출력도 없다 — 선 없이 혼자 계산하는 도구. */
export const isSolo = (c: Pick<NodeCatalogEntry, "inputs" | "outputs">): boolean => c.inputs.length === 0 && c.outputs.length === 0;

/** 바꾼 뒤 선마다 새 포트 이름(선 id → 포트). 맞출 수 없으면 null. */
export function swapPlan(id: string, kind: string, nodes: SwapNode[], edges: SwapEdge[], catalog: NodeCatalogEntry[]):
    { inputs: Record<string, string>; outputs: Record<string, string> } | null {
  const cur = catalog.find((c) => c.type === nodes.find((n) => n.id === id)?.data.kind);
  const next = catalog.find((c) => c.type === kind);
  if (!cur || !next) return null;
  const inputs: Record<string, string> = {};
  const taken = new Set<string>();
  // 같은 이름 자리를 먼저 맞추고, 남은 선을 같은 타입의 빈 자리에 — 순서 때문에 이름이 같은 자리를 빼앗기지 않게 두 번 돈다.
  const incoming = edges.filter((e) => e.target === id);
  const typeIn = (e: SwapEdge) => cur.inputs.find((p) => p.name === e.targetHandle)?.type;
  for (const e of incoming) {
    const same = next.inputs.find((p) => p.name === e.targetHandle && p.type === typeIn(e));
    if (same && !taken.has(same.name)) { inputs[e.id] = same.name; taken.add(same.name); }
  }
  for (const e of incoming) {
    if (inputs[e.id]) continue;
    const t = typeIn(e);
    const free = next.inputs.find((p) => p.type === t && !taken.has(p.name));
    if (!t || !free) return null;
    inputs[e.id] = free.name;
    taken.add(free.name);
  }
  const outputs: Record<string, string> = {};
  for (const e of edges.filter((x) => x.source === id)) {
    const t = cur.outputs.find((p) => p.name === e.sourceHandle)?.type;
    const o = next.outputs.find((p) => p.name === e.sourceHandle && p.type === t) ?? next.outputs.find((p) => p.type === t);
    if (!t || !o) return null;
    outputs[e.id] = o.name;
  }
  return { inputs, outputs };
}

/** 바꿔 끼울 수 있는 종류 — 같은 단계, 지금 선을 모두 다시 맞출 수 있는 것만. */
export function swapCandidates(id: string, nodes: SwapNode[], edges: SwapEdge[], catalog: NodeCatalogEntry[]): NodeCatalogEntry[] {
  const kind = nodes.find((n) => n.id === id)?.data.kind;
  const cur = catalog.find((c) => c.type === kind);
  if (!cur) return [];
  return catalog.filter((c) => c.type !== kind && c.stage === cur.stage && swapPlan(id, c.type, nodes, edges, catalog) !== null);
}

/** 고른 노드의 출력을 받을 수 있는 종류 — 단계 순서, 같은 단계는 카탈로그 순서, 혼자 도구는 뺀다. */
export function nextKinds(kind: string, catalog: NodeCatalogEntry[], stageOrder: string[], limit = 5): NodeCatalogEntry[] {
  const outTypes = new Set(catalog.find((c) => c.type === kind)?.outputs.map((p) => p.type) ?? []);
  if (!outTypes.size) return [];
  const rank = (s: string) => { const i = stageOrder.indexOf(s); return i < 0 ? stageOrder.length : i; };
  return catalog
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => !isSolo(c) && c.inputs.some((p) => outTypes.has(p.type)))
    .sort((a, b) => rank(a.c.stage) - rank(b.c.stage) || a.i - b.i)
    .slice(0, limit)
    .map(({ c }) => c);
}
