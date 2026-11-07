/**
 * 묻기 범위(AI3) — 서버 `src/services/canvas_assist/ask.py::scope` 와 같은 규칙(사용자 결정 2026-10-23: 고른 것 + 위쪽 전부 + 바로 아래).
 *  · 노드: 조상 전부 + 그 노드 + 바로 아래 · 선 = 양끝이 위쪽에 있는 선 + 그 노드에서 자식으로 가는 선(조상에서 자식으로 바로 가는 선은 뺀다).
 *  · 선(s→t): s 의 조상 + s + t · 선 = 위쪽 안의 선 + 그 선.
 * 화면은 이것으로 ① 머리 줄의 "위쪽 n · 아래 m" ② 문답이 기댄 결과가 바뀌었는지(범위 안 봉인 묶음)를 잰다. 근거는 서버가 다시 고른다.
 */
import type { AskTarget } from "./types";

type E = { id: string; source: string; target: string };

function ancestors(id: string, edges: E[]): Set<string> {
  const up = new Map<string, string[]>();
  for (const e of edges) up.set(e.target, [...(up.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const todo = [id];
  while (todo.length) {
    for (const s of up.get(todo.pop()!) ?? []) if (!seen.has(s)) { seen.add(s); todo.push(s); }
  }
  seen.delete(id);
  return seen;
}

export interface AskScope { nodes: Set<string>; edges: Set<string>; up: number; down: number }

export function askScope(target: AskTarget, nodeIds: string[], edges: E[]): AskScope | null {
  const ids = new Set(nodeIds);
  if (target.kind === "node") {
    if (!ids.has(target.id)) return null;
    const anc = ancestors(target.id, edges);
    const upper = new Set([...anc, target.id]);
    const kids = new Set(edges.filter((e) => e.source === target.id && ids.has(e.target)).map((e) => e.target));
    const keep = edges.filter((e) => (upper.has(e.source) && upper.has(e.target)) || (e.source === target.id && kids.has(e.target)));
    return { nodes: new Set([...upper, ...kids]), edges: new Set(keep.map((e) => e.id)), up: anc.size, down: kids.size };
  }
  const edge = edges.find((e) => e.id === target.id);
  if (!edge || !ids.has(edge.source) || !ids.has(edge.target)) return null;
  const anc = ancestors(edge.source, edges);
  const upper = new Set([...anc, edge.source]);
  const keep = edges.filter((e) => upper.has(e.source) && upper.has(e.target)).map((e) => e.id);
  return { nodes: new Set([...upper, edge.target]), edges: new Set([...keep, edge.id]), up: anc.size, down: 0 };
}
